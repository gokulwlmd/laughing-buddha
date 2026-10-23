/* Shared ID photo picker. Images stay in memory until an explicit upload. */
(() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  class IDUpload extends HTMLElement {
    constructor(){super();this.attachShadow({mode:'open'});this.busy=false;this.error='';this.photo=null;this.version=0;this.shadowRoot.addEventListener('change',e=>{if(e.target.type==='file')this.choose(e.target.files?.[0]);});this.shadowRoot.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action==='clear'){this.version++;this.photo=null;this.error='';this.render();}if(action==='send')this.send(false);if(action==='reuse'||action==='retry')this.send(true);if(action==='reload')this.load();if(action==='continue')this.dispatchEvent(new CustomEvent('id-uploaded',{bubbles:true,composed:true}));});}
    configure(api){if(this.api)return;this.api=api;this.load();}
    disconnectedCallback(){this.version++;this.photo=null;}
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
      const info=this.info,attached=info?.order_attached,review=info?.status==='needs_review';
      this.shadowRoot.innerHTML=`<style>:host{display:block;color:inherit;font:inherit;margin-top:24px}*{box-sizing:border-box}.panel{padding:clamp(20px,3vw,32px);border:1px solid #ded8d0;border-radius:18px;background:var(--id-background,#faf8f4)}h3{font-size:23px;margin:0 0 12px;line-height:1.3}p{font-size:17px;line-height:1.6;margin:12px 0}.hint{font-size:14px;color:#625d56}.actions{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}button,.picker{position:relative;display:inline-flex;justify-content:center;align-items:center;font:inherit;font-weight:600;font-size:16px;min-height:52px;padding:12px 18px;border-radius:10px;border:1px solid #a89588;background:transparent;color:inherit;cursor:pointer;overflow:hidden}.primary{color:white;background:var(--brand,var(--intake-accent,#245844));border-color:transparent}button:disabled{opacity:.6;cursor:wait}.picker input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.picker:focus-within,button:focus-visible{outline:3px solid #245844;outline-offset:3px}img{display:block;max-width:100%;max-height:280px;object-fit:contain;margin:20px auto;border-radius:8px}.saved{display:inline-block;font-size:14px;font-weight:600;padding:6px 12px;border-radius:20px;background:#e9f3ed;color:#22533a}.error{color:#962b20}@media(max-width:500px){.actions>*{flex:1 1 100%}}</style><section class="panel" aria-busy="${this.busy}"><h3>${attached?'Your ID photo is saved':'Photo ID'}</h3>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${this.busy?'<p role="status">'+(this.phase||'Preparing your photo…')+'</p>':attached?`<span class="saved">Uploaded</span><p>Added to this order. You can reuse this photo for future orders with this site.</p><p class="hint">Uploaded ${esc(new Date(info.uploaded_at).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}))}</p>${this.hasAttribute('intake')?'<button class="primary" data-action="continue">Continue to intake</button>':''}`:review?'<p>Your last upload could not be confirmed. Your photo is saved securely, so you don’t need to choose it again.</p><div class="actions"><button class="primary" data-action="retry">Retry saved photo</button><button data-action="reload">Check upload status</button></div>':info?.saved?'<p>Your ID is already saved. Use it for this order without taking another photo.</p><button class="primary" data-action="reuse">Use saved ID for this order</button>':info?.available?`<p>Prefer to use an ID instead of your SSN? Upload a photo or use your phone’s camera. Include all four corners and make sure the text is clear.</p>${this.photo?`<img src="${this.photo}" alt="Your selected ID photo — check that the text is clear"><div class="actions"><button class="primary" data-action="send">Upload this photo</button><button data-action="clear">Choose another photo</button></div>`:`<div class="actions"><label class="picker">Upload ID<input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" aria-label="Upload ID"></label><label class="picker">Take photo<input type="file" accept="image/*" capture="environment" aria-label="Take photo of ID"></label></div>`}<p class="hint">Your photo is sent securely and kept encrypted for reuse with your account on this site.</p>`:'<p>ID uploads are temporarily unavailable. You can use the SSN option instead.</p><button data-action="reload">Try again</button>'}</section>`;
    }
  }
  if(!customElements.get('wlmd-id-upload'))customElements.define('wlmd-id-upload',IDUpload);
})();
