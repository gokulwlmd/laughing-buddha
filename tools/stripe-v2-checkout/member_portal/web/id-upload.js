/* Shared ID photo picker. Images stay in memory until an explicit upload. */
(() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  class IDUpload extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});this.busy=false;this.error='';this.photo=null;this.version=0;this.shadowRoot.addEventListener('change',e=>{if(e.target.type==='file')this.choose(e.target.files?.[0]);});this.shadowRoot.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action==='camera')this.openCamera();if(action==='camera-close')this.closeCamera();if(action==='camera-capture')this.captureCamera();if(action==='camera-retake')this.openCamera();if(action==='camera-use'){const photo=this.cameraPhoto;this.closeCamera();this.photo=photo;this.send(false);}if(action==='clear'){this.version++;this.photo=null;this.error='';this.render();}if(action==='send')this.send(false);if(action==='reuse'||action==='retry')this.send(true);if(action==='reload')this.load();if(action==='continue')this.dispatchEvent(new CustomEvent('id-uploaded',{bubbles:true,composed:true}));});}
    configure(api){if(this.api)return;this.api=api;this.load();}
    disconnectedCallback(){this.version++;this.photo=null;this.closeCamera();}
    closeCamera(){
      this.cameraVersion=(this.cameraVersion||0)+1;
      clearInterval(this.cameraTimer);this.cameraTimer=null;this.cameraPrevious=null;this.cameraSteady=0;
      this.cameraStream?.getTracks().forEach(track=>track.stop());this.cameraStream=null;
      const video=this.shadowRoot.querySelector('video');if(video)video.srcObject=null;
      document.removeEventListener('visibilitychange',this.cameraVisibility);
      this.cameraDialog?.close();this.cameraDialog?.remove();this.cameraDialog=null;
      this.cameraPhoto=null;
    }
    cameraShell(title){
      const dialog=document.createElement('dialog');dialog.className='camera-dialog';
      dialog.setAttribute('aria-label',title);
      dialog.addEventListener('cancel',e=>{e.preventDefault();this.closeCamera();});
      this.shadowRoot.append(dialog);this.cameraDialog=dialog;dialog.showModal();return dialog;
    }
    async openCamera(){
      if(this.busy)return;
      this.closeCamera();this.error='';
      const version=this.cameraVersion,dialog=this.cameraShell('Take a photo of your ID');
      dialog.innerHTML=`<div class="camera-head"><h3>Take a photo of your ID</h3><button data-action="camera-close" aria-label="Close camera">✕</button></div><p class="camera-help">Fit all four corners inside the frame. Hold still and we’ll take the photo.</p><div class="viewfinder"><video autoplay muted playsinline></video><div class="id-frame" aria-hidden="true"></div></div><p class="camera-status" role="status">Allow camera access to get started.</p><div class="actions"><button class="primary" data-action="camera-capture" disabled>Take photo now</button><button data-action="camera-close">Cancel</button></div><p class="hint">Your camera stays on this device. You’ll review the photo before uploading it.</p>`;
      this.cameraVisibility=()=>{if(document.hidden)this.closeCamera();};document.addEventListener('visibilitychange',this.cameraVisibility);
      try{
        if(!navigator.mediaDevices?.getUserMedia)throw Error('Camera access is unavailable in this browser. You can upload an ID photo instead.');
        const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}}});
        if(version!==this.cameraVersion||!this.isConnected){stream.getTracks().forEach(track=>track.stop());return;}
        this.cameraStream=stream;const video=dialog.querySelector('video');video.srcObject=stream;await video.play();
        if(version!==this.cameraVersion)return;
        dialog.querySelector('[data-action="camera-capture"]').disabled=false;
        dialog.querySelector('.camera-status').textContent='Fit your ID inside the frame and hold still.';
        this.cameraPrevious=null;this.cameraSteady=0;
        this.cameraTimer=setInterval(()=>this.checkCamera(),200);
      }catch(e){
        if(version!==this.cameraVersion)return;
        this.closeCamera();this.error=e.name==='NotAllowedError'?'Camera permission was not granted. Allow access in your browser, or choose Upload ID.':e.name==='NotFoundError'?'No camera was found. Choose Upload ID to use a saved photo.':e.name==='NotReadableError'?'Your camera is busy. Close other camera apps and try again, or choose Upload ID.':e.message||'We couldn’t open your camera. Choose Upload ID instead.';this.render();
      }
    }
    cameraCrop(){
      const video=this.cameraDialog?.querySelector('video'),frame=this.cameraDialog?.querySelector('.id-frame');
      if(!video?.videoWidth||!frame)return null;
      const v=video.getBoundingClientRect(),f=frame.getBoundingClientRect(),scale=Math.max(v.width/video.videoWidth,v.height/video.videoHeight);
      return {video,x:(f.left-v.left+(video.videoWidth*scale-v.width)/2)/scale,y:(f.top-v.top+(video.videoHeight*scale-v.height)/2)/scale,w:f.width/scale,h:f.height/scale};
    }
    checkCamera(){
      const crop=this.cameraCrop();if(!crop)return;
      const canvas=document.createElement('canvas');canvas.width=160;canvas.height=100;const ctx=canvas.getContext('2d',{willReadFrequently:true});
      ctx.drawImage(crop.video,crop.x,crop.y,crop.w,crop.h,0,0,160,100);
      const pixels=ctx.getImageData(0,0,160,100).data,gray=new Uint8Array(16000);let sum=0,squares=0,motion=0,edges=0;
      for(let i=0;i<gray.length;i++){const value=(pixels[i*4]+pixels[i*4+1]+pixels[i*4+2])/3;gray[i]=value;sum+=value;squares+=value*value;if(this.cameraPrevious)motion+=Math.abs(value-this.cameraPrevious[i]);if(i%160>0&&Math.abs(value-gray[i-1])>25)edges++;}
      const mean=sum/gray.length,contrast=Math.sqrt(Math.max(0,squares/gray.length-mean*mean)),detail=edges/gray.length;
      const clear=mean>45&&mean<235&&contrast>22&&detail>.025,steady=this.cameraPrevious&&motion/gray.length<3.5;
      this.cameraPrevious=gray;this.cameraSteady=clear&&steady?this.cameraSteady+200:0;
      const status=this.cameraDialog.querySelector('.camera-status');
      const message=mean<=45?'Move to a brighter spot.':!clear?'Fit your ID in the frame. Avoid glare and keep the text clear.':!steady?'Hold your ID steady.':`Hold still… taking your photo in ${Math.max(1,Math.ceil((2200-this.cameraSteady)/1000))}`;
      if(status.textContent!==message)status.textContent=message;
      this.cameraDialog.querySelector('.id-frame').classList.toggle('ready',Boolean(clear&&steady));
      if(this.cameraSteady>=2200)this.captureCamera();
    }
    captureCamera(){
      const crop=this.cameraCrop();if(!crop)return;
      if(Math.min(crop.w,crop.h)<200){this.cameraDialog.querySelector('.camera-status').textContent='Camera resolution is too low. Upload a clearer photo instead.';return;}
      const canvas=document.createElement('canvas'),scale=Math.min(1,2400/Math.max(crop.w,crop.h));canvas.width=Math.round(crop.w*scale);canvas.height=Math.round(crop.h*scale);
      canvas.getContext('2d').drawImage(crop.video,crop.x,crop.y,crop.w,crop.h,0,0,canvas.width,canvas.height);
      const photo=canvas.toDataURL('image/jpeg',.92);canvas.width=canvas.height=0;
      this.closeCamera();this.cameraPhoto=photo;
      const dialog=this.cameraShell('Review your ID photo');
      dialog.innerHTML=`<div class="camera-head"><h3>Check your photo</h3><button data-action="camera-close" aria-label="Close photo review">✕</button></div><p>Make sure all four corners are visible and the text is easy to read.</p><img class="camera-preview" src="${photo}" alt="Your captured ID photo"><div class="actions"><button class="primary" data-action="camera-use">Use photo</button><button data-action="camera-retake">Retake</button></div><p class="hint">Choose Use photo to securely upload this ID.</p>`;
    }
    async load(){this.busy=true;this.phase='Checking your saved ID…';this.error='';this.render();try{this.info=await this.api.load();}catch(e){this.error=e.message||'Your ID photo status is unavailable.';}finally{this.busy=false;if(this.isConnected)this.render();}if(this.isConnected&&this.hasAttribute('intake')&&this.info?.saved&&!this.info.order_attached&&this.info.status!=='needs_review'&&this.info.available)await this.send(true);}
    async choose(file){
      if(!file||this.busy)return;
      const current=++this.version;this.photo=null;this.error='';this.busy=true;this.phase='Preparing your photo…';this.render();

      try{
        if(!file.type.startsWith('image/')||file.type==='image/svg+xml'||file.size>20*1024*1024)throw Error('Choose a photo smaller than 20 MB. JPG, PNG and WebP work best.');
        const source=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('We couldn’t read this photo. Please try another.'));reader.readAsDataURL(file);});const img=new Image();img.src=source;await img.decode();
        if(current!==this.version)return;
        if(img.width*img.height>24_000_000||Math.min(img.width,img.height)<200)throw Error('Choose a clear photo with at least 200 pixels on each side and no more than 24 megapixels.');
        const scale=Math.min(1,2400/Math.max(img.width,img.height)),canvas=document.createElement('canvas');canvas.width=Math.round(img.width*scale);canvas.height=Math.round(img.height*scale);
        const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height);
        const photo=canvas.toDataURL('image/jpeg',.92);canvas.width=canvas.height=0;
        if(photo.length>7*1024*1024)throw Error('This photo is too large. Please take a closer photo of your ID.');
        this.photo=photo;
      }catch(e){if(current===this.version)this.error=e.message||'We couldn’t open this photo. Try a JPG or take another photo.';}
      finally{if(current===this.version){this.busy=false;this.render();}}
    }
    async send(reuse){
      if(this.busy||(!reuse&&!this.photo))return;
      let contents=this.photo?.split(',')[1];this.photo=null;this.busy=true;this.phase='Uploading your ID securely…';this.error='';this.render();
      try{this.info=await this.api.upload(reuse?null:{file_contents:contents});if(this.info.order_attached)this.dispatchEvent(new CustomEvent('id-uploaded',{bubbles:true,composed:true}));}
      catch(e){this.error=e.message||'We couldn’t confirm your upload. Please check its status before trying again.';try{this.info=await this.api.load();}catch(_) {this.info={status:'needs_review'};}}
      finally{contents='';this.busy=false;if(this.isConnected)this.render();}
    }
    render(){
      this.closeCamera();
      const info=this.info,attached=info?.order_attached,review=info?.status==='needs_review';
      this.shadowRoot.innerHTML=`<style>:host{display:block;color:inherit;font:inherit;margin-top:24px}*{box-sizing:border-box}.panel{padding:clamp(20px,3vw,32px);border:1px solid #ded8d0;border-radius:18px;background:var(--id-background,#faf8f4)}h3{font-size:23px;margin:0 0 12px;line-height:1.3}p{font-size:17px;line-height:1.6;margin:12px 0}.hint{font-size:14px;color:#625d56}.actions{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}button,.picker{position:relative;display:inline-flex;justify-content:center;align-items:center;font:inherit;font-weight:600;font-size:16px;min-height:52px;padding:12px 18px;border-radius:10px;border:1px solid #a89588;background:transparent;color:inherit;cursor:pointer;overflow:hidden}.primary{color:white;background:var(--brand,var(--intake-accent,#245844));border-color:transparent}button:disabled{opacity:.6;cursor:wait}.picker input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.picker:focus-within,button:focus-visible{outline:3px solid #245844;outline-offset:3px}img{display:block;max-width:100%;max-height:280px;object-fit:contain;margin:20px auto;border-radius:8px}.saved{display:inline-block;font-size:14px;font-weight:600;padding:6px 12px;border-radius:20px;background:#e9f3ed;color:#22533a}.error{color:#962b20}.camera-dialog{width:min(760px,calc(100vw - 24px));max-height:94dvh;overflow:auto;overscroll-behavior:contain;border:0;border-radius:22px;padding:clamp(18px,4vw,30px);color:#202b26;background:#faf8f4;font:inherit}.camera-dialog::backdrop{background:rgb(10 22 17 / .78)}.camera-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.camera-head h3{margin:0}.camera-head button{flex:none;min-width:48px;padding:10px}.camera-dialog p{font-size:16px}.viewfinder{position:relative;aspect-ratio:4/3;background:#17231f;overflow:hidden;border-radius:14px;margin-top:18px}.viewfinder video{position:absolute;width:100%;height:100%;object-fit:cover}.id-frame{position:absolute;width:86%;aspect-ratio:1.586;left:7%;top:50%;transform:translateY(-50%);border:3px solid white;border-radius:12px;box-shadow:0 0 0 100vmax rgb(0 0 0 / .45);transition:border-color .2s}.id-frame.ready{border-color:#83e6ae}.camera-status{min-height:48px;font-weight:600}.camera-preview{max-height:52dvh;width:100%;object-fit:contain}.camera-dialog .actions{margin-bottom:12px}@media(max-width:500px){.actions>*{flex:1 1 100%}}</style><section class="panel" aria-busy="${this.busy}"><h3>${attached?'Your ID photo is saved':'Photo ID'}</h3>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${this.busy?'<p role="status">'+(this.phase||'Preparing your photo…')+'</p>':attached?`<span class="saved">Uploaded</span><p>Added to this order. You can reuse this photo for future orders with this site.</p><p class="hint">Uploaded ${esc(new Date(info.uploaded_at).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}))}</p>${this.hasAttribute('intake')?'<button class="primary" data-action="continue">Continue to intake</button>':''}`:review?'<p>Your last upload could not be confirmed. Your photo is saved securely, so you don’t need to choose it again.</p><div class="actions"><button class="primary" data-action="retry">Retry saved photo</button><button data-action="reload">Check upload status</button></div>':info?.saved?'<p>Your ID is already saved. Use it for this order without taking another photo.</p><button class="primary" data-action="reuse">Use saved ID for this order</button>':info?.available?`<p>Prefer to use an ID instead of your SSN? Upload a photo or use your phone’s camera. Include all four corners and make sure the text is clear.</p>${this.photo?`<img src="${this.photo}" alt="Your selected ID photo — check that the text is clear"><div class="actions"><button class="primary" data-action="send">Upload this photo</button><button data-action="clear">Choose another photo</button></div>`:`<div class="actions"><label class="picker">Upload ID<input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" aria-label="Upload ID"></label><button data-action="camera" aria-label="Take photo of ID">Take photo</button></div>`}<p class="hint">Your photo is sent securely and kept encrypted for reuse with your account on this site.</p>`:'<p>ID uploads are temporarily unavailable. You can use the SSN option instead.</p><button data-action="reload">Try again</button>'}</section>`;
    }
  }
  if(!customElements.get('wlmd-id-upload'))customElements.define('wlmd-id-upload',IDUpload);
})();
