/* Shared post-purchase intake and Sticky password setup. No provider credentials. */
(() => {
  'use strict';
  const origin = new URL(document.currentScript.src).origin;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  class PurchaseIntake extends HTMLElement {
    constructor() { super(); this.attachShadow({mode:'open'}); this.shadowRoot.addEventListener('input',e=>this.input(e));this.shadowRoot.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action)this.action(action);}); this.shadowRoot.addEventListener('submit',e=>{e.preventDefault();if(e.target.id==='account-form')this.action('account-save');});this.orders=[]; this.index=0; this.dirty=0; this.saved=0; this.pending=null; this.busy=false; this.error=''; this.missing=[]; this.exit=e=>{if(this.dirty>this.saved){e.preventDefault();e.returnValue='';}}; }
    connectedCallback(){window.addEventListener('beforeunload',this.exit);}
    disconnectedCallback(){window.removeEventListener('beforeunload',this.exit);clearTimeout(this.timer);}
    async configure({siteId,sessions}) {
      if(this.configured) return;
      if(!/^[a-zA-Z0-9_-]+$/.test(siteId)||!Array.isArray(sessions)||!sessions.length||sessions.length>20) throw new Error('Invalid intake configuration');
      this.configured=true;this.site=siteId;
      this.orders=sessions.filter(s=>typeof s.session_id==='string'&&typeof s.session_token==='string');
      this.render();await Promise.all([this.load(),this.loadAccount()]);
    }
    async api(suffix,method='GET',body,session=this.orders[this.index]) {
      const response=await fetch(`${origin}/api/v1/sites/${encodeURIComponent(this.site)}/sessions/${encodeURIComponent(session.session_id)}${suffix}`,{method,credentials:'omit',cache:'no-store',headers:{Authorization:`Bearer ${session.session_token}`,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
      const data=await response.json();
      if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'We couldn’t save this step. Please check your answers and try again.');error.status=response.status;error.questions=data.detail?.question_ids;throw error;}
      return data;
    }
    async loadAccount(){
      try{this.account=await this.api('/account','GET',undefined,this.orders[0]);}catch(e){this.accountError='Your purchase is saved. Portal password setup is temporarily unavailable.';}finally{this.render();}
    }
    accountPanel(){
      if(!this.account&&!this.accountError)return '';
      const state=this.account?.state;
      if(state==='ready')return '<section class="panel account"><h2>Your portal password is saved</h2><p>Use your purchase email and this password to access your orders, deliveries and saved intake.</p><button class="secondary" data-action="portal">Open member portal</button></section>';
      if(state==='sign_in')return '<section class="panel account"><h2>Your member account is ready</h2><p>Use your existing member password in the portal. Your new purchase does not change it.</p><button class="secondary" data-action="portal">Open member portal</button></section>';
      if(state==='needs_review'||!state)return `<section class="panel account"><h2>Your member portal</h2><p role="status">${esc(this.accountError||'Your purchase is saved. Contact support to finish account setup.')}</p><button class="secondary" data-action="account-reload">Check account setup</button><button class="secondary" data-action="portal">Open member portal</button></section>`;
      return `<section class="panel account"><h2>Set your member portal password</h2><p>Track your orders, manage deliveries and finish your intake later. No email step needed.</p>${this.accountError?`<p class="error" role="alert">${esc(this.accountError)}</p>`:''}<form id="account-form"><label for="new-password">Choose a password</label><input id="new-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required aria-describedby="password-help"><p id="password-help" class="meta">Use at least 12 characters.</p><label for="confirm-password">Confirm password</label><input id="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required><div class="actions"><button type="submit" ${this.accountBusy?'disabled':''}>${this.accountBusy?'Saving password…':'Save portal password'}</button></div></form></section>`;
    }
    async saveAccount(){
      const form=this.shadowRoot.querySelector('#account-form');if(!form||!form.reportValidity())return;
      let password=form.querySelector('#new-password').value;
      if(password!==form.querySelector('#confirm-password').value){this.accountError='The passwords do not match. Please enter them again.';this.render();return;}
      this.accountBusy=true;this.accountError='';this.render();
      try{
        // Every cart item needs its own verified receipt. The same password
        // authenticates existing membership; it never overwrites it.
        for(const session of this.orders)await this.api('/account','POST',{password},session);
        this.account={...this.account,state:'ready'};
      }catch(e){this.accountError=e.message;}
      finally{password='';this.accountBusy=false;this.render();}
    }
    async load(){this.busy=true;this.error='';this.render();try{this.form=await this.api('/intake');this.answers={...this.form.answers};this.dirty=this.saved=0;this.missing=[];}catch(e){this.error=e.message;}finally{this.busy=false;this.render();}}
    visible(q){return !q.show_if||this.answers[q.show_if.question_id]===q.show_if.equals;}
    async flush(){
      clearTimeout(this.timer);
      if(this.pending) {await this.pending; if(this.error)return false;}
      if(this.dirty===this.saved)return true;
      const version=this.dirty,answers=structuredClone(this.answers),step=this.form.current_step;
      this.pending=this.api('/intake','PATCH',{revision:this.form.revision,answers,current_step:step}).then(data=>{this.form=data;this.saved=version;this.error='';}).catch(e=>{this.error=e.status===409?'This intake changed in another window. Your unsaved answers are still here. Reload the page after checking the other window.':e.message;}).finally(()=>{this.pending=null;this.status();});
      await this.pending;
      if(this.error)return false;
      return this.dirty>this.saved?this.flush():true;
    }
    status(){const node=this.shadowRoot.querySelector('[data-save]');if(node)node.textContent=this.error|| (this.dirty>this.saved?'Saving your answers…':'Your answers are saved');}
    focus(){const node=this.shadowRoot.querySelector('h2');node?.focus({preventScroll:true});this.scrollIntoView({block:'start',behavior:'instant'});}
    field(q){const value=this.answers[q.id],id=`q-${q.id}`;let input;
      if(q.type==='single_choice'||q.type==='multi_choice')input=q.options.map((o,i)=>`<label class="choice"><input id="${esc(id+'-'+i)}" data-q="${esc(q.id)}" type="${q.type==='single_choice'?'radio':'checkbox'}" name="${esc(q.id)}" value="${esc(o.value)}" ${(q.type==='single_choice'?value===o.value:Array.isArray(value)&&value.includes(o.value))?'checked':''}>${esc(o.label)}</label>`).join('');
      else input=q.type==='textarea'?`<textarea aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" rows="3" maxlength="1000">${esc(value)}</textarea>`:`<input aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" type="${q.type==='number'?'number':'text'}" ${q.type==='number'?'step="any"':'maxlength="1000"'} value="${esc(value)}">`;
      return `<fieldset><legend>${esc(q.label)} ${q.required?'':'<small>(optional)</small>'}</legend>${input}${this.missing.includes(q.id)?'<p class="error">Please answer this question.</p>':''}</fieldset>`;
    }
    render(){
      const f=this.form,sections=f?.template.sections||[],step=f?.current_step||0,section=sections[step];
      this.shadowRoot.innerHTML=`<style>:host{display:block;scroll-margin-top:110px;color:inherit;font:inherit}*{box-sizing:border-box}.account{margin-bottom:24px!important}.account label{display:block;margin:16px 0 8px;font-weight:600}.panel{max-width:820px;margin:0 auto;border:1px solid #dedbd5;background:#fff;border-radius:20px;padding:clamp(20px,4vw,40px)}h2{font-size:clamp(24px,4vw,32px);line-height:1.25;margin:12px 0}p{line-height:1.6}.meta,small{color:#62625c}fieldset{border:0;padding:0;margin:26px 0}legend{font-weight:600;font-size:18px;line-height:1.5;margin-bottom:12px}input:not([type=radio]):not([type=checkbox]),textarea{width:100%;font:inherit;font-size:17px;border:1px solid #aaa;border-radius:8px;padding:13px;background:#fff;color:#222}input[type=radio],input[type=checkbox]{width:21px;height:21px;flex:none;accent-color:var(--intake-accent,#245844)}.choice{display:flex;gap:12px;align-items:center;min-height:52px;border:1px solid #ddd;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}button,a{font:inherit;font-weight:600;font-size:16px;min-height:48px;border-radius:8px;padding:12px 18px;cursor:pointer}button{background:var(--intake-accent,#245844);color:white;border:0}button.secondary{background:#f1f0eb;color:#222}button:disabled{opacity:.6;cursor:wait}.actions{display:flex;gap:12px;flex-wrap:wrap;justify-content:space-between;margin-top:28px}.error{color:#a52822}.save{min-height:24px;font-size:14px}a{color:inherit;display:inline-flex;align-items:center}progress{width:100%;height:8px;accent-color:var(--intake-accent,#245844)}:focus-visible{outline:3px solid #245844;outline-offset:3px}.portal{border-top:1px solid #ddd;margin-top:28px;padding-top:20px}</style>${this.accountPanel()}<section class="panel" aria-busy="${this.busy}"><p class="meta">Health intake${this.orders.length>1?` · Product ${this.index+1} of ${this.orders.length}`:''}</p><h2 tabindex="-1">${esc(f?.template.title||'Your next step')}</h2>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${!f?`<p>${this.busy?'Opening your intake…':'Your order is saved. Please try opening your intake again.'}</p><button data-action="reload" ${this.busy?'disabled':''}>Try again</button>`:f.status==='submitted'?`<p>Your intake has been submitted. You can view your order and follow your next steps in your member portal.</p>${this.index<this.orders.length-1?'<button data-action="next-product">Continue to next product</button>':''}`:`<p class="meta">Step ${step+1} of ${sections.length} · ${esc(section?.title)}</p><progress value="${step+1}" max="${sections.length}"></progress><p>${esc(section?.description)}</p><form novalidate>${f.template.questions.filter(q=>q.section_id===section?.id&&this.visible(q)).map(q=>this.field(q)).join('')}<p class="save" data-save aria-live="polite"></p><div class="actions">${step?'<button type="button" class="secondary" data-action="back">Back</button>':'<span></span>'}<button type="button" data-action="${step===sections.length-1?'submit':'next'}" ${this.busy?'disabled':''}>${this.busy?'Saving…':step===sections.length-1?'Submit intake':'Continue'}</button></div></form>`}<div class="portal"><p>You can also finish your intake in your member portal.</p><button class="secondary" data-action="portal" ${this.busy?'disabled':''}>Open member portal</button>${this.portalLink?`<p><a href="${esc(this.portalLink)}">Continue to member portal →</a></p>`:''}</div></section>`;
      this.status();
    }
    input(e){const el=e.target,id=el.dataset.q;if(!id||!this.form)return;const q=this.form.template.questions.find(q=>q.id===id);this.answers[id]=q.type==='multi_choice'?[...this.shadowRoot.querySelectorAll('input[type=checkbox]:checked')].filter(n=>n.dataset.q===id).map(n=>n.value):q.type==='number'?(el.value===''?null:Number(el.value)):el.value;this.dirty++;this.error='';this.missing=this.missing.filter(x=>x!==id);if(['single_choice','multi_choice'].includes(q.type)){this.render();this.shadowRoot.getElementById(el.id)?.focus({preventScroll:true});}this.status();clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush(),500);}
    async action(action){
      if(this.busy||this.acting||this.accountBusy)return;this.acting=true;
      try{await this.performAction(action);}finally{this.acting=false;}
    }
    async performAction(action){
      if(action==='account-save'){await this.saveAccount();return;}
      if(action==='account-reload'){await this.loadAccount();return;}
      if(action==='reload'){await this.load();return;}
      if(this.form&&this.form.status!=='submitted'&&!await this.flush()){this.render();return;}
      if(action==='portal'){
        this.busy=true;this.error='';this.render();
        try{const links=await Promise.all(this.orders.map(s=>this.api('/portal','POST',{},s)));const expected=`/portal/${encodeURIComponent(links[0].site_id)}`;const urls=links.map(l=>new URL(l.enrollment_url));if(urls.some(u=>u.origin!==origin||u.pathname!==expected))throw new Error('The member portal link could not be verified.');const tokens=urls.map(u=>new URLSearchParams(u.hash.slice(1)).get('invite')).filter(Boolean);const url=new URL(expected,origin);if(tokens.length)url.hash=new URLSearchParams({invites:JSON.stringify(tokens)}).toString();this.portalLink=url.href;window.location.assign(url.href);}catch(e){this.error=e.message;}finally{this.busy=false;this.render();}return;
      }
      if(action==='next-product'){this.index++;this.form=null;await this.load();this.focus();return;}
      const sections=this.form.template.sections,step=this.form.current_step;
      if(action==='next'||action==='submit'){this.missing=this.form.template.questions.filter(q=>this.visible(q)&&q.required&&(action==='submit'||q.section_id===sections[step].id)&&[undefined,null,''].includes(this.answers[q.id])||this.visible(q)&&q.required&&(action==='submit'||q.section_id===sections[step].id)&&Array.isArray(this.answers[q.id])&&!this.answers[q.id].length).map(q=>q.id);if(this.missing.length){this.error='Please complete the highlighted questions.';this.render();this.shadowRoot.querySelector('.error')?.scrollIntoView({block:'center'});return;}}
      this.busy=true;this.error='';
      try{if(action==='submit'){this.form=await this.api('/intake/submit','POST',{revision:this.form.revision});}else{this.form.current_step=Math.max(0,Math.min(sections.length-1,step+(action==='back'?-1:1)));this.dirty++;await this.flush();}}catch(e){this.error=e.message;this.missing=e.questions||[];}finally{this.busy=false;this.render();this.focus();}
    }
  }
  if(!customElements.get('wlmd-purchase-intake'))customElements.define('wlmd-purchase-intake',PurchaseIntake);
})();
