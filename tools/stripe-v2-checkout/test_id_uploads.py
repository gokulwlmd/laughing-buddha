"""Generated photos and offline WLMD fixtures only."""
import base64
import io
import json
import unittest
from PIL import Image
from fastapi import HTTPException
from member_portal.id_uploads import IDPhotoInput, UploadProvider, normalize_photo, MAX_BODY_BYTES
import test_member_portal as fixtures


def photo():
    out=io.BytesIO(); image=Image.new('RGB',(640,400),'#c0c0c0')
    exif=Image.Exif();exif[270]='SYNTHETIC METADATA TO REMOVE'
    image.save(out,format='JPEG',exif=exif)
    return base64.b64encode(out.getvalue()).decode()


class FakeUpload:
    def __init__(self): self.calls=[];self.result=json.dumps({'db_id':1,'s3_key':'fixture/private.jpg'})
    def available(self): return True
    def upload(self,site,order,contents):
        self.calls.append((site,order,contents));return self.result


class PhotoTests(unittest.TestCase):
    setUp=fixtures.MemberPortalTests.setUp
    tearDown=fixtures.MemberPortalTests.tearDown
    post_owner=fixtures.MemberPortalTests.post_owner
    enroll=fixtures.MemberPortalTests.enroll

    def configure(self,enroll=True):
        if enroll:self.enroll()
        raw=self.service.admin.get('site','site-a');raw['wlmd_site_id']='qa-site';self.service.admin.put('site','site-a',raw)
        self.uploads=self.service.id_uploads;self.fake_upload=FakeUpload();self.uploads.provider=self.fake_upload
        self.path=self.base+'/orders/9001/id-photo'

    def test_upload_alternative_and_encryption(self):
        self.configure();raw=photo()
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,409)
        result=self.client.post(self.path,headers=self.patient_headers,json={'file_contents':raw})
        self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['order_attached'])
        self.assertNotIn('s3_key',result.text)
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)
        self.assertEqual(self.client.get(self.base+'/account/identity',headers=self.patient_headers).json()['status'],'needed')
        with self.service.db() as db:record=dict(db.execute('SELECT * FROM member_id_uploads').fetchone())
        self.assertNotIn(raw,json.dumps(record));self.assertNotIn('fixture/private.jpg',record['reference'])
        normalized=self.uploads.cipher.decrypt(record['photo'].encode()).decode()
        with Image.open(io.BytesIO(base64.b64decode(normalized))) as image:self.assertFalse(image.getexif())
        self.assertEqual(self.client.post(self.path,headers=self.patient_headers,json={'file_contents':raw}).status_code,200)
        self.assertEqual(len(self.fake_upload.calls),1)

    def test_adoption_and_reuse_on_new_order(self):
        self.configure(enroll=False);order,guest=self.service.receipt_order(self.app.state.store.read(self.attempt))
        self.uploads.upload(order,guest,IDPhotoInput(file_contents=photo()));self.enroll()
        with self.service.db() as db:patient={'id':db.execute("SELECT patient_id FROM member_grants WHERE order_id='9001'").fetchone()[0]}
        self.assertTrue(self.uploads.status(order,patient)['saved'])
        other=dict(order);other['order_id']='9002'
        self.assertFalse(self.uploads.status(other,patient)['order_attached'])
        result=self.uploads.upload(other,patient)
        self.assertTrue(result['order_attached']);self.assertEqual(len(self.fake_upload.calls),2)
        self.assertEqual(self.fake_upload.calls[0][2],self.fake_upload.calls[1][2]);self.assertEqual(self.fake_upload.calls[1][1],'9002')
        self.assertFalse(self.uploads.status(other,{'id':'receipt:9002','_reuse_allowed':False})['saved'])
        self.assertFalse(self.uploads.status(other,{'id':'different-patient'})['saved'])
        other['site_id']='site-b';self.assertFalse(self.uploads.status(other,patient)['saved'])

    def test_authentication_ownership_and_validation(self):
        self.configure();self.assertEqual(self.client.get(self.path).status_code,401)
        self.assertEqual(self.client.post(self.path.replace('9001','9999'),headers=self.patient_headers,json={'file_contents':photo()}).status_code,404)
        for contents in ['NOT_A_PHOTO',base64.b64encode(b'<svg>test</svg>').decode()]:
            response=self.client.post(self.path,headers=self.patient_headers,json={'file_contents':contents})
            self.assertEqual(response.status_code,422);self.assertNotIn(contents,response.text)
        response=self.client.post(self.path,headers=self.patient_headers,json={'file_contents':'PRIVATE','order_id':'wrong'})
        self.assertEqual(response.status_code,422);self.assertNotIn('PRIVATE',response.text)
        response=self.client.post(self.path,headers=self.patient_headers,content=b' '*(MAX_BODY_BYTES+1))
        self.assertEqual(response.status_code,413);self.assertEqual(self.fake_upload.calls,[])

    def test_uncertain_upload_requires_explicit_rate_limited_retry(self):
        self.configure();self.fake_upload.result=None
        result=self.client.post(self.path,headers=self.patient_headers,json={'file_contents':photo()})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.client.get(self.path,headers=self.patient_headers).json()['status'],'needs_review')
        self.assertEqual(self.client.post(self.path+'/reuse',headers=self.patient_headers).status_code,429)
        self.assertEqual(len(self.fake_upload.calls),1)
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,409)
        now=self.service.clock();self.service.clock=lambda:now+31
        self.fake_upload.result='confirmed-reference'
        response=self.client.post(self.path+'/reuse',headers=self.patient_headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'uploaded')
        self.assertEqual(len(self.fake_upload.calls),2)

    def test_confirmed_response_contract(self):
        provider=UploadProvider();good={'status':'success','data':{'db_id':1,'s3_key':'fixture/ID.jpg','orders_dictionary_key':'FUT:ID'},'message':'PRIVATE MESSAGE'}
        self.assertEqual(json.loads(provider.parse_result(good)),{'db_id':1,'s3_key':'fixture/ID.jpg'})
        for result in [{},[],{'status':'success'},{**good,'status':'pending'},{**good,'data':{**good['data'],'orders_dictionary_key':'OTHER'}}]:self.assertIsNone(provider.parse_result(result))

    def test_provider_accepts_decimal_string_upload_id_but_not_invalid_ids(self):
        provider=UploadProvider()
        result={'status':'success','data':{'db_id':'42','s3_key':'fixture/ID.jpg','orders_dictionary_key':'FUT:ID'}}
        self.assertEqual(json.loads(provider.parse_result(result)),{'db_id':42,'s3_key':'fixture/ID.jpg'})
        for invalid in [None,True,False,0,-1,1.5,'','0','-1','1.5',' 123 ','１２３','1e3','9'*21,{},[]]:
            with self.subTest(db_id=invalid):
                self.assertIsNone(provider.parse_result({**result,'data':{**result['data'],'db_id':invalid}}))

    def test_string_id_provider_success_unblocks_intake_and_saves_reference(self):
        self.configure()
        provider=UploadProvider()
        self.fake_upload.result=provider.parse_result({'status':'success','data':{'db_id':'42','s3_key':'fixture/ID.jpg','orders_dictionary_key':'FUT:ID'}})
        self.fake_upload.result_before=self.fake_upload.result
        self.fake_upload.result=None
        self.assertEqual(self.client.post(self.path,headers=self.patient_headers,json={'file_contents':photo()}).status_code,409)
        now=self.service.clock();self.service.clock=lambda:now+31
        self.fake_upload.result=self.fake_upload.result_before
        response=self.client.post(self.path+'/reuse',headers=self.patient_headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['order_attached'])
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)
        self.assertEqual(len(self.fake_upload.calls),2)
        with self.service.db() as db:
            row=db.execute("SELECT reference FROM member_id_uploads WHERE status='uploaded'").fetchone()
        self.assertEqual(json.loads(self.uploads.cipher.decrypt(row['reference'].encode())),{'db_id':42,'s3_key':'fixture/ID.jpg'})

    def test_pre_intake_dictionary_upload_succeeds_without_internal_database_id(self):
        self.configure()
        provider=UploadProvider()
        response={'status':'success','data':{'db_id':'','s3_key':'fixture/ID.jpg','orders_dictionary_key':'FUT:ID','file_size_bytes':97557}}
        reference=provider.parse_result(response)
        self.assertEqual(json.loads(reference),{'db_id':None,'s3_key':'fixture/ID.jpg','storage':'orders_dictionary'})
        self.fake_upload.result=reference
        result=self.client.post(self.path,headers=self.patient_headers,json={'file_contents':photo()})
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(result.json()['order_attached'])
        self.assertEqual(self.client.get(self.base+'/intakes/9001',headers=self.patient_headers).status_code,200)
        for patch in [{'file_size_bytes':0},{'file_size_bytes':True},{'file_size_bytes':'97557'},{'s3_key':''},{'orders_dictionary_key':'OTHER'},{'db_id':None}]:
            self.assertIsNone(provider.parse_result({**response,'data':{**response['data'],**patch}}))
        self.assertIsNone(provider.parse_result({**response,'status':'error'}))

    def test_image_size_dimensions_and_truncation(self):
        for size in [(10,10),(6000,5000)]:
            buf=io.BytesIO();Image.new('RGB',size).save(buf,format='PNG')
            with self.assertRaises(HTTPException):normalize_photo(base64.b64encode(buf.getvalue()).decode())
        with self.assertRaises(HTTPException):normalize_photo(photo()[:100])

class StreamingLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_body_is_rejected_before_handler(self):
        from member_portal.upload_limits import IDUploadBodyLimit
        called=[];sent=[];chunks=[{'type':'http.request','body':b'x'*(4*1024*1024),'more_body':True},{'type':'http.request','body':b'x'*(4*1024*1024),'more_body':False}]
        async def receive():return chunks.pop(0)
        async def send(message):sent.append(message)
        async def handler(*args):called.append(True)
        await IDUploadBodyLimit(handler)({'type':'http','method':'POST','path':'/api/post-checkout-id-photo','headers':[]},receive,send)
        self.assertEqual(called,[]);self.assertEqual(sent[0]['status'],413)
