/* Shared post-purchase intake and Sticky password setup. No provider credentials. */
(() => {
  'use strict';
  const origin = new URL(document.currentScript.src).origin;
  let idComponent;
  const loadIDComponent=()=>idComponent||(idComponent=import(origin+'/portal-assets/id-upload.js'));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function matchesCondition(c,a){if(c.all)return c.all.every(x=>matchesCondition(x,a));if(c.any)return c.any.some(x=>matchesCondition(x,a));const v=a[c.question_id],empty=v==null||v===''||Array.isArray(v)&&!v.length;if(c.operator==='isEmpty')return empty;if(empty)return false;if(c.operator==='isFilled')return true;if(c.operator==='equals')return Array.isArray(v)?v.includes(c.value):v===c.value;if(c.operator==='notEquals')return Array.isArray(v)?!v.includes(c.value):v!==c.value;if(c.operator==='contains')return v.includes(c.value);if(c.operator==='notContains')return !v.includes(c.value);return false;}
  class PurchaseIntake extends HTMLElement {
    constructor() { super(); this.attachShadow({mode:'open'}); this.shadowRoot.addEventListener('pointerdown',e=>{const button=e.target.closest('button[data-action]');if(button&&!button.disabled&&e.button===0){e.preventDefault();}}); this.shadowRoot.addEventListener('input',e=>this.input(e));this.shadowRoot.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action)this.action(action,e.target.closest('[data-action]')?.dataset.q);}); this.shadowRoot.addEventListener('submit',e=>{e.preventDefault();if(e.target.id==='account-form')this.action('account-save');if(e.target.id==='identity-form')this.action('identity-verify');});this.offers={};this.offerResults={};this.orders=[]; this.intakeStates=[]; this.linkedAccounts=new Set(); this.journeys=[]; this.journeyErrors=[]; this.index=0; this.started=false; this.dirty=0; this.saved=0; this.pending=null; this.busy=false; this.error=''; this.missing=[]; this.exit=e=>{if(this.dirty>this.saved){e.preventDefault();e.returnValue='';}}; }
    connectedCallback(){window.addEventListener('beforeunload',this.exit);}
    disconnectedCallback(){window.removeEventListener('beforeunload',this.exit);clearTimeout(this.timer);}
    async configure({siteId,sessions}) {
      if(this.configured) return;
      if(!/^[a-zA-Z0-9_-]+$/.test(siteId)||!Array.isArray(sessions)||!sessions.length||sessions.length>20) throw new Error('Invalid intake configuration');
      this.configured=true;this.site=siteId;
      this.orders=sessions.filter(s=>typeof s.session_id==='string'&&typeof s.session_token==='string');
      if(this.orders.length!==sessions.length)throw new Error('Invalid purchase sessions');
      this.render();await Promise.all([this.load(),this.loadAccount(),this.loadJourneys()]);void this.loadOffers();
    }
    async api(suffix,method='GET',body,session=this.orders[this.index]) {
      const response=await fetch(`${origin}/api/v1/sites/${encodeURIComponent(this.site)}/sessions/${encodeURIComponent(session.session_id)}${suffix}`,{method,credentials:'omit',cache:'no-store',headers:{Authorization:`Bearer ${session.session_token}`,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
      const data=await response.json();
      if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:data.detail?.message||'We couldn’t save this step. Please check your answers and try again.');error.status=response.status;error.detail=data.detail;error.questions=data.detail?.question_ids;throw error;}
      return data;
    }
    async loadOffers(refresh=false){
      const index=this.index,placements=this.form?.status==='submitted'?['after_intake']:['thank_you','before_intake'];
      for(const placement of placements){const cache=index+':'+placement;if(!refresh&&this.offers[cache])continue;try{const result=await this.api('/offers?placement='+placement,'GET',undefined,this.orders[index]);this.offers[cache]=result.offers||[];}catch(_error){this.offers[cache]=[];}}
      this.render();
    }
    offersPanel(placement){
      const offers=this.offers[this.index+':'+placement]||[];
      if(!offers.length)return '';
      return `<section class="panel offer-panel"><p class="meta">OPTIONAL · ONE-TIME PURCHASES</p><h2>Explore more care</h2><p>Use the payment method and delivery address from your order. Each product has its own intake and review.</p>${offers.map(o=>{const result=this.offerResults[o.quote_id],price=new Intl.NumberFormat('en-US',{style:'currency',currency:o.currency}).format(o.amount/100);return `<article class="offer-card"><h3>${esc(o.name)}</h3><p>${esc(o.plan_name)} · ${esc(price)}</p><p class="meta">${esc(o.terms)}</p>${result?`<p role="status">${esc(result.message)}</p>`:`<button data-action="buy-offer" data-q="${esc(o.quote_id)}" ${this.busy?'disabled':''}>Buy for ${esc(price)}</button>`}</article>`;}).join('')}<p class="meta">Buying is optional. Continue your intake whenever you’re ready.</p></section>`;
    }
    async loadJourney(index,refresh=false){
      try{this.journeys[index]=await this.api('/journey'+(refresh?'?refresh=true':''),'GET',undefined,this.orders[index]);this.journeyErrors[index]='';}
      catch(e){this.journeyErrors[index]='Order updates are temporarily unavailable.';}
    }
    async loadJourneys(refresh=false){
      // Bound parallel reads for larger carts. A failed item must not block
      // another purchased item's intake or discard its completed steps.
      for(let start=0;start<this.orders.length;start+=2){
        await Promise.all(this.orders.slice(start,start+2).map((_,n)=>this.loadJourney(start+n,refresh)));this.render();
      }
    }
    intakeComplete(index){
      return (this.intakeStates[index]??this.journeys[index]?.intake_status)==='submitted';
    }
    rememberIntake(){if(this.form)this.intakeStates[this.index]=this.form.status;}
    canAutoSignIn(){
      return this.linkedAccounts.size===this.orders.length&&!!this.handoff&&Number.isFinite(this.handoffExpires)&&this.handoffExpires>Date.now()+5000;
    }
    productTabs(){
      if(this.orders.length<2)return '';
      const complete=this.orders.filter((_,i)=>this.intakeComplete(i)).length;
      return `<div class="product-switch"><p class="meta">${complete} of ${this.orders.length} complete</p><nav class="products" aria-label="Purchased products">${this.orders.map((_,i)=>`<button class="secondary" data-action="select-product" data-q="${i}" ${i===this.index?'aria-current="true"':''} ${this.busy?'disabled':''}>${esc((this.journeys[i]?.product_name||`Product ${i+1}`).replace(/\s*(?:·|\/)\s*\d+[- ]months?.*$/i,''))}<small>${this.intakeComplete(i)?'Complete':'Health intake'}</small></button>`).join('')}</nav></div>`;
    }
    intakeHeader(){
      const item=this.journeys[this.index];
      return `<header class="intake-top"><button class="text-button" data-action="back-to-order">Back to order</button><span class="meta">${item?`Order #${esc(item.id)}`:'Your health intake'}</span></header>${this.productTabs()}`;
    }
    progressPanel(){
      const ready=['ready','sign_in'].includes(this.account?.state)||(!this.account&&!this.accountError),complete=this.orders.every((_,i)=>this.intakeComplete(i));
      return `<section class="panel purchase-progress" aria-label="Purchase and next steps"><p class="eyebrow">PURCHASE CONFIRMED</p><h2>Congratulations!<br>Your order is placed.</h2><div class="order-receipts">${this.orders.map((_,i)=>{const item=this.journeys[i];return `<div class="receipt-row"><p>${esc((item?.product_name||'Your treatment').replace(/ \/ /g,' · ').replace('1 months','1 month'))}</p><strong>${item?`Order #${esc(item.id)}`:'Your order is confirmed'}</strong></div>`;}).join('')}</div>${ready?`<p>${complete?'Your health intake is saved. See what happens next in your care plan.':'Next, a few questions about your health.'}</p><button class="wide" data-action="start-intake" ${this.busy?'disabled':''}>${complete?'See my next steps':this.form?.current_step?'Continue health intake':'Start health intake'}</button>`:''}</section>`;
    }
    async loadAccount(){
      try{this.account=await this.api('/account','GET',undefined,this.orders[0]);}catch(e){this.accountError='Your purchase is saved. Portal password setup is temporarily unavailable.';}finally{this.render();}
    }
    accountPanel(){
      if(!this.account&&!this.accountError)return '';
      const state=this.account?.state;
      if(state==='ready')return `<section class="account-ready"><h2>Your portal password is saved</h2><p>${this.canAutoSignIn()?'Finish your intake, then open your care plan without signing in again.':'Finish your intake, then use your password to open your member portal.'}</p></section>`;
      if(state==='sign_in')return '<div class="account-ready">✓ Your existing member account is ready. Finish your intake below.</div>';
      if(state==='needs_review'||!state)return `<section class="panel account"><h2>Your member portal</h2><p role="status">${esc(this.accountError||'Your purchase is saved. Contact support to finish account setup.')}</p><button data-action="start-intake">Start health intake</button><button class="secondary" data-action="account-reload">Check account setup</button><button class="secondary" data-action="portal">Open member portal</button></section>`;
      return `<section class="panel account"><p class="eyebrow">YOUR NEXT STEP</p><h2>Set your password</h2><p>${this.linkedAccounts.size?'Your password is saved. Enter the same password to finish connecting the remaining products.':'Your member portal keeps your treatment, deliveries and refills in one place.'}</p>${this.accountError?`<p class="error" role="alert">${esc(this.accountError)}</p>`:''}<form id="account-form"><div class="password-fields"><div><label for="new-password">Choose a password</label><input id="new-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required aria-describedby="password-help"><p id="password-help" class="meta">Use at least 12 characters.</p></div><div><label for="confirm-password">Confirm password</label><input id="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></div></div><div class="actions"><button type="submit" ${this.accountBusy?'disabled':''}>${this.accountBusy?'Saving…':'Set password & continue'}</button></div></form><p class="next-hint">Next: a few questions about your health.</p><button class="text-button skip" data-action="start-intake">Set up later · continue to intake</button><button class="text-button" data-action="portal">Open member portal</button></section>`;
    }
    async saveAccount(){
      const form=this.shadowRoot.querySelector('#account-form');if(!form||!form.reportValidity())return;
      let password=form.querySelector('#new-password').value;
      if(password!==form.querySelector('#confirm-password').value){this.accountError='The passwords do not match. Please enter them again.';this.render();return;}
      this.accountBusy=true;this.accountError='';this.render();
      try{
        // Every cart item needs its own verified receipt. The same password
        // authenticates existing membership; it never overwrites it.
        for(const session of this.orders){
          if(this.linkedAccounts.has(session.session_id))continue;
          const result=await this.api('/account','POST',{password},session);
          this.linkedAccounts.add(session.session_id);
          this.handoff=result.portal_handoff||null;
          this.handoffExpires=Date.parse(result.handoff_expires_at);
        }
        this.account={...this.account,state:'ready'};this.started=true;void this.loadOffers(true);
      }catch(e){this.accountError=e.message;}
      finally{password='';this.accountBusy=false;this.render();if(this.started)this.focus();}
    }
    async load(){this.identityGate=null;this.busy=true;this.error='';this.render();try{this.form=await this.api('/intake');this.rememberIntake();this.answers={...this.form.answers};this.dirty=this.saved=0;this.missing=[];}catch(e){if(e.detail?.code==='identity_verification_required'){this.form=null;this.identityGate=true;}else this.error=e.message;}finally{this.busy=false;this.render();}}
    visible(q){return (!q.show_if||this.answers[q.show_if.question_id]===q.show_if.equals)&&(!q.show_when||matchesCondition(q.show_when,this.answers));}
    async flush(){
      clearTimeout(this.timer);
      while(this.pending) {await this.pending; if(this.error)return false;}
      if(this.dirty===this.saved)return true;
      const version=this.dirty,answers=structuredClone(this.answers),step=this.form.current_step;
      this.pending=this.api('/intake','PATCH',{revision:this.form.revision,answers,current_step:step}).then(data=>{this.form=data;this.rememberIntake();this.saved=version;this.error='';}).catch(e=>{this.error=e.status===409?'This intake changed in another window. Your unsaved answers are still here. Reload the page after checking the other window.':e.message;}).finally(()=>{this.pending=null;this.status();});
      await this.pending;
      if(this.error)return false;
      return this.dirty>this.saved?this.flush():true;
    }
    status(){const node=this.shadowRoot.querySelector('[data-save]');if(node)node.textContent=this.error?this.error:(this.dirty>this.saved?'Saving your answers…':'Your answers are saved');}
    focus(){const panel=this.shadowRoot.querySelector('.panel[aria-busy]');panel?.querySelector('h2')?.focus({preventScroll:true});panel?.scrollIntoView({block:'start',behavior:'instant'});}
    field(q,editing=false){
      if(q.reuse_policy==='verified')return `<fieldset><legend>${esc(q.label)}</legend><p>${q.reuse_status==='verified'?'Verified · saved securely':'Complete verification with the identity service to continue.'}</p></fieldset>`;
      if(q.reuse_status==='stable'&&!editing)return `<fieldset class="saved-answer"><legend>${esc(q.label)}</legend><p>${esc(this.answers[q.id])}</p><details><summary aria-label="Change saved answer: ${esc(q.label)}">Edit</summary><div class="edit-field">${this.field(q,true)}</div></details></fieldset>`;
      const previous=q.reuse_status==='confirm'?`<p>Previously: ${esc(q.saved_value)}</p><p>Confirm this is still correct, or enter an updated answer below.</p><button type="button" class="secondary" data-action="confirm-saved" data-q="${esc(q.id)}">Still correct</button>`:'';
      const value=this.answers[q.id],id=`q-${q.id}`;let input;
      if(q.type==='single_choice'&&(q.presentation==='select'||q.options.length>6))input=`<select aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}"><option value="">Select an option</option>${q.options.map(o=>`<option value="${esc(o.value)}" ${value===o.value?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`;
      else if(q.type==='single_choice'||q.type==='multi_choice')input=q.options.map((o,i)=>`<label class="choice"><input id="${esc(id+'-'+i)}" data-q="${esc(q.id)}" type="${q.type==='single_choice'?'radio':'checkbox'}" name="${esc(q.id)}" value="${esc(o.value)}" ${(q.type==='single_choice'?value===o.value:Array.isArray(value)&&value.includes(o.value))?'checked':''}>${esc(o.label)}</label>`).join('');
      else input=q.type==='textarea'?`<textarea aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" rows="3" maxlength="1000">${esc(value)}</textarea>`:`<input aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" type="${q.type==='number'?'number':['email','tel','date'].includes(q.input_type)?q.input_type:'text'}" ${q.type==='number'?'step="any"':'maxlength="1000"'} value="${esc(value)}">`;
      return `<fieldset><legend>${esc(q.label)} ${q.required?'':'<small>(optional)</small>'}</legend>${q.hint?`<p class="meta">${esc(q.hint)}</p>`:''}${previous}${input}${this.missing.includes(q.id)?'<p class="error">Please answer this question.</p>':''}</fieldset>`;
    }
    sectionFields(section){
      const questions=this.form.template.questions.filter(q=>q.section_id===section?.id&&this.visible(q));
      const saved=questions.filter(q=>q.reuse_status==='stable'&&q.reuse_policy!=='verified');
      if(!saved.length)return questions.map(q=>this.field(q)).join('');
      const source=saved.every(q=>q.prefill_source==='checkout')?'From your checkout':saved.every(q=>q.prefill_source!=='checkout')?'Saved from your previous intake':'Your saved details';
      return `<div class="saved-details"><p class="detail-source">${source}</p>${saved.map(q=>this.field(q)).join('')}</div>${questions.filter(q=>!saved.includes(q)).map(q=>this.field(q)).join('')}`;
    }
    render(){
      const active=this.shadowRoot.activeElement,activeId=active?.id;
      const ephemeral={};
      if(!this.accountBusy)for(const id of ['new-password','confirm-password','identity-last4']){const node=this.shadowRoot.getElementById(id);if(node)ephemeral[id]=node.value;}
      const f=this.form,sections=f?.template.sections||[],step=f?.current_step||0,section=sections[step],visibleSteps=sections.map((s,i)=>({s,i})).filter(({s,i})=>i===sections.length-1||f.template.questions.some(q=>q.section_id===s.id&&this.visible(q)));const displayStep=Math.max(1,visibleSteps.findIndex(x=>x.i===step)+1);
      this.shadowRoot.innerHTML=`<style>
:host{display:block;--intake-accent:#a8563b;--ink:#25241f;--muted:#706b63;--line:#e5e1da;--wash:#f8f7f4;color:var(--ink);font:inherit;font-size:16px;line-height:1.5;scroll-margin-top:24px}
*{box-sizing:border-box}[hidden]{display:none!important}h2,h3,p{margin:0}h2{font-size:26px;font-weight:600;letter-spacing:-.035em;line-height:1.25}h3{font-size:18px}p{line-height:1.55}.meta,small{color:var(--muted)}.eyebrow{font-size:10px;font-weight:600;letter-spacing:.16em;color:var(--muted);margin:0 0 12px}
button,a,input,select,textarea{font:inherit}button,a{font-size:14px;font-weight:600;min-height:46px;border-radius:7px;padding:12px 18px;cursor:pointer}button{background:var(--intake-accent);border:1px solid transparent;color:#fff;line-height:1.4;transition:background .15s,border-color .15s}button:hover:not(:disabled){filter:brightness(.96)}button:disabled{opacity:.6;cursor:wait}button.secondary{background:var(--wash);border-color:var(--line);color:var(--ink)}a{color:inherit;display:inline-flex;align-items:center}:focus-visible{outline:2px solid var(--intake-accent);outline-offset:3px}.text-button{background:none;color:var(--muted);border:0;font-size:13px;font-weight:500;padding:10px 0;min-height:44px}.text-button:hover{color:var(--ink)}
.panel{width:100%;max-width:640px;margin:auto;padding:28px 32px;background:#fff}.welcome-shell{max-width:680px;margin:8px auto 28px;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 8px 32px #29231b05}.welcome-shell .panel{max-width:none}.purchase-progress{padding:30px 36px 20px;background:var(--wash)}.purchase-progress h2{font-size:30px;line-height:1.15;letter-spacing:-.045em;margin-bottom:22px}.order-receipts{border-top:1px solid var(--line);padding-top:8px}.receipt-row{padding:10px 0;display:flex;align-items:baseline;justify-content:space-between;gap:20px}.receipt-row+.receipt-row{border-top:1px solid var(--line)}.receipt-row p{font-size:14px;line-height:1.5;font-weight:500}.receipt-row strong{font-size:12px;font-weight:500;color:var(--muted);white-space:nowrap}.purchase-progress>p:not(.eyebrow){font-size:14px;margin:16px 0}.wide{width:100%}.account{padding:26px 36px 18px}.account h2{font-size:23px;margin-bottom:8px}.account>p:not(.eyebrow):not(.next-hint){font-size:14px;color:var(--muted);max-width:430px}.account .eyebrow{margin-bottom:8px}.password-fields{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}.account label{display:block;font-size:13px;font-weight:500;margin-bottom:8px}.account #password-help{font-size:11px;margin:6px 0 0;color:var(--muted)}.account .actions{margin-top:18px}.account .actions button{width:100%;min-height:48px}.account .next-hint{text-align:center;font-size:12px;color:var(--muted);margin-top:10px}.account>.text-button{display:block;margin:0 auto}.account>.text-button:not(.skip){min-height:32px;font-size:12px;padding:4px 0 8px}.account>.skip{margin-top:4px;font-size:12px}.account-ready{max-width:640px;margin:auto;padding:10px 32px 0}.account-ready h2{font-size:12px;font-weight:500;letter-spacing:0;color:var(--muted)}.account-ready p{font-size:13px;color:var(--muted)}
input:not([type=radio]):not([type=checkbox]),textarea,select{width:100%;font-size:16px;min-height:48px;line-height:1.4;padding:12px 14px;border:1px solid #c7c3bb;border-radius:7px;background:#fff;color:var(--ink)}textarea{resize:vertical}input[type=radio],input[type=checkbox]{height:20px;width:20px;flex:none;margin:0;accent-color:var(--intake-accent)}fieldset{border:0;padding:0;margin:20px 0;min-width:0}legend{font-size:16px;line-height:1.45;font-weight:500;margin-bottom:10px;width:100%}legend small{font-size:12px;font-weight:400}fieldset>.meta{font-size:13px;margin:0 0 10px}.choice{display:flex;gap:12px;align-items:center;min-height:54px;border:1px solid var(--line);border-radius:8px;padding:13px 16px;margin:8px 0;cursor:pointer;font-size:15px}.choice:hover{border-color:#b4aa9d}.choice:has(input:checked){border-color:var(--intake-accent);background:#faf5f1}.error{color:#a52822;font-size:14px;margin:12px 0}.save{font-size:11px;color:var(--muted);min-height:20px;margin:12px 0}
.intake-top{max-width:640px;margin:auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line)}.intake-top .meta{font-size:11px}.intake-panel{padding-top:24px;scroll-margin-top:16px}.intake-panel>p.meta:first-child{font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;margin-bottom:10px}.intake-panel h2{font-size:28px}.step-count{font-size:12px;color:var(--muted);margin-top:12px}progress{appearance:none;display:block;width:100%;height:3px;border:0;border-radius:3px;overflow:hidden;background:var(--line);margin:10px 0 20px;accent-color:var(--intake-accent)}progress::-webkit-progress-bar{background:var(--line)}progress::-webkit-progress-value{background:var(--intake-accent)}progress::-moz-progress-bar{background:var(--intake-accent)}.section-description{font-size:14px;color:var(--muted);margin-bottom:20px}.intake-panel form:not(#identity-form){display:flex;flex-direction:column;min-height:280px}.intake-panel form>fieldset:first-child{margin-top:0}.actions{display:flex;gap:12px;justify-content:space-between}.intake-panel .actions{position:sticky;bottom:0;z-index:2;background:#fff;border-top:1px solid var(--line);padding:14px 0 max(14px,env(safe-area-inset-bottom));margin-top:auto;flex-wrap:nowrap}.intake-panel .actions button:last-child{flex:1}.intake-panel .actions button{min-height:50px}.portal{text-align:center}.portal .text-button{font-size:12px}.portal p{overflow-wrap:anywhere}
.saved-details{border:1px solid var(--line);border-radius:10px;padding:0 18px;margin:0 0 8px;background:#fff}.detail-source{font-size:11px;color:var(--muted);padding:12px 0;border-bottom:1px solid var(--line)}fieldset.saved-answer{position:relative;margin:0;padding:12px 60px 12px 0;border-bottom:1px solid var(--line)}fieldset.saved-answer:last-child{border:0}.saved-answer legend{float:left;font-size:12px;font-weight:500;color:var(--muted);margin:0 0 4px}.saved-answer>p{clear:both;font-size:15px;line-height:1.5;overflow-wrap:anywhere}.saved-answer summary{position:absolute;right:0;top:16px;cursor:pointer;font-size:12px;font-weight:500;color:var(--intake-accent);min-height:44px;padding:4px 0;list-style:none}.saved-answer summary::-webkit-details-marker{display:none}.saved-answer details[open]{padding-top:10px}.saved-answer:has(details[open]){padding-right:0}.saved-answer details[open] summary{top:16px}.edit-field fieldset{margin:8px 0}.edit-field legend{float:none;font-size:13px;color:var(--ink);margin-bottom:8px}.saved-answer:has(details[open])>p{padding-right:55px}.saved-answer:has(details[open])>legend{padding-right:55px}
.product-switch{max-width:640px;padding:12px 32px 0;margin:auto}.product-switch>.meta{font-size:11px}.products{display:flex;gap:8px;margin:8px 0 0;flex-wrap:wrap}.products button{flex:1;min-width:120px;text-align:left;font-size:12px;font-weight:500;padding:10px 12px;line-height:1.4;background:#fff}.products small{display:block;font-size:10px;margin-top:4px}.products [aria-current]{border-color:var(--intake-accent);background:#faf5f1}.next-steps{list-style:none;padding:0;margin:24px 0;display:grid;gap:20px}.next-steps li{padding-left:16px;border-left:2px solid var(--intake-accent);font-size:15px}.next-steps span{display:block;font-size:14px;color:var(--muted);margin-top:5px}.offer-panel{margin-top:24px;border-top:1px solid var(--line)}.offer-panel>p{font-size:13px;color:var(--muted);margin:12px 0}.offer-card{padding:18px 0;border-top:1px solid var(--line)}.offer-card p{font-size:14px;margin:8px 0}.offer-card .meta{font-size:12px}#identity-form{margin-top:20px}#identity-form label{font-size:14px}#identity-form .meta{font-size:12px;margin:10px 0 16px}.intake-panel>p:not([class]){font-size:14px;color:var(--muted);margin:12px 0}
@media(max-width:600px){:host{width:100vw;max-width:none;margin-left:calc(50% - 50vw);background:#fff;font-size:16px}.panel{max-width:none;width:100%;padding:24px 20px}.welcome-shell{margin:0;border:0;border-radius:0;box-shadow:none}.purchase-progress{padding:24px 20px 18px}.purchase-progress h2{font-size:28px;margin-bottom:18px}.receipt-row{display:block;padding:10px 0}.receipt-row p{font-size:14px}.receipt-row strong{display:block;margin-top:4px}.account{padding-top:24px;padding-bottom:16px}.account h2{font-size:23px}.account>p:not(.eyebrow):not(.next-hint){font-size:14px}.password-fields{grid-template-columns:1fr;gap:16px;margin-top:18px}.account label{font-size:14px}.account .actions button{min-height:52px}.account .next-hint{font-size:11px}.intake-top{padding:0 20px}.account-ready{padding:10px 20px 0}.intake-panel{min-height:calc(100svh - 116px);display:flex;flex-direction:column;padding-top:22px;padding-bottom:0}.intake-panel h2{font-size:26px}.intake-panel form:not(#identity-form){flex:1;min-height:260px}.intake-panel .actions{margin-left:-20px;margin-right:-20px;padding-left:20px;padding-right:20px}.intake-panel .actions button{min-height:52px}.product-switch{padding:10px 20px 0}.saved-details{padding:0 14px}.saved-answer>p{font-size:15px}.portal{padding-bottom:env(safe-area-inset-bottom)}.offer-panel{margin-top:12px}.welcome-shell .account-ready{padding:16px 20px}}
@media(prefers-reduced-motion:reduce){button{transition:none}}
</style>${this.started?this.intakeHeader()+(this.account?.state==='ready'&&step===0?'<div class="account-ready" role="status"><h2>Your portal password is saved</h2></div>':''):'<div class="welcome-shell">'+this.progressPanel()+this.accountPanel()+'</div>'+this.offersPanel('thank_you')+this.offersPanel('before_intake')}<section class="panel intake-panel" ${this.started?'':'hidden'} aria-busy="${this.busy}"><p class="meta">Health intake${this.orders.length>1?` · Product ${this.index+1} of ${this.orders.length}`:''}</p><h2 tabindex="-1">${esc(this.identityGate?'One last step: verify your identity':f?.status==='submitted'?'Your intake is saved':section?.title||f?.template.title||'Your next step')}</h2>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${this.identityGate?`<p>Your health answers are saved. Choose a photo of your ID or the last four digits of your SSN to finish your intake.</p><form id="identity-form"><label for="identity-last4">Last 4 digits of your SSN</label><input id="identity-last4" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="off" required aria-describedby="identity-privacy" style="display:block;max-width:220px;letter-spacing:.35em;font-size:24px;margin-top:12px"><p id="identity-privacy" class="meta">We don’t store your SSN digits.</p><button type="submit" ${this.busy?'disabled':''}>${this.busy?'Verifying…':'Verify & finish intake'}</button></form><wlmd-id-upload intake></wlmd-id-upload>`:!f?`<p>${this.busy?'Opening your intake…':'Your order is saved. Please try opening your intake again.'}</p><button data-action="reload" ${this.busy?'disabled':''}>Try again</button>`:f.status==='submitted'?`<p>Your intake has been submitted. Your answers are saved with this order.</p><ol class="next-steps"><li><strong>Check your care plan</strong><span>See this order’s status and any remaining tasks in your member portal.</span></li><li><strong>Follow your delivery</strong><span>Your tracking link appears when the order ships.</span></li><li><strong>Manage your next supply</strong><span>Your treatment shows your refill date and what is included.</span></li></ol>${this.orders.some((_,i)=>i!==this.index&&!this.intakeComplete(i))?'<button data-action="next-product">Finish another product’s intake</button>':'<button data-action="portal">Go to my care plan →</button>'}`:`<p class="step-count">Step ${displayStep} of ${visibleSteps.length}</p><progress aria-label="Health intake progress" value="${displayStep}" max="${visibleSteps.length}"></progress>${section?.description&&section.description!=='Your progress is saved automatically.'?`<p class="section-description">${esc(section.description)}</p>`:''}<form novalidate>${this.sectionFields(section)}<p class="save" data-save aria-live="polite"></p><div class="actions">${step?'<button type="button" class="secondary" data-action="back">Back</button>':'<span></span>'}<button type="button" data-action="${step===sections.length-1?'submit':'next'}" ${this.busy?'disabled':''}>${this.busy?'Saving…':step===sections.length-1?'Submit intake':'Continue'}</button></div></form>`}<div class="portal"><button class="text-button" data-action="portal" ${this.busy?'disabled':''}>Open member portal</button>${this.portalLink?`<p><a href="${esc(this.portalLink)}">Continue to member portal →</a></p>`:''}</div></section>${this.started?this.offersPanel('after_intake'):''}`;
      for(const [id,value] of Object.entries(ephemeral)){const node=this.shadowRoot.getElementById(id);if(node)node.value=value;}
      if(activeId)this.shadowRoot.getElementById(activeId)?.focus({preventScroll:true});
      this.status();
      const el=this.shadowRoot.querySelector('wlmd-id-upload');
      if(el){const session=this.orders[this.index];loadIDComponent().then(()=>{if(!el.isConnected)return;el.configure({load:()=>this.api('/id-photo','GET',undefined,session),upload:body=>this.api('/id-photo'+(body?'':'/reuse'),'POST',body||{},session)});el.addEventListener('id-uploaded',()=>this.finishIdentity(),{once:true});}).catch(()=>{el.textContent='The photo option could not load. Refresh the page or use your SSN.';});}
    }
    async finishIdentity(){this.identityGate=null;this.busy=true;this.error='';try{if(!this.form)await this.load();this.form=await this.api('/intake/submit','POST',{revision:this.form.revision});this.rememberIntake();await this.loadJourney(this.index);void this.loadOffers();}catch(e){if(e.detail?.code==='identity_verification_required')this.identityGate=true;this.error=e.message;}finally{this.busy=false;this.render();this.focus();}}
    input(e){const el=e.target,id=el.dataset.q;if(!id||!this.form)return;const q=this.form.template.questions.find(q=>q.id===id);this.answers[id]=q.type==='multi_choice'?[...this.shadowRoot.querySelectorAll('input[type=checkbox]:checked')].filter(n=>n.dataset.q===id).map(n=>n.value):q.type==='number'?(el.value===''?null:Number(el.value)):el.value;if(q.type==='multi_choice'&&q.exclusive_options?.length){if(el.checked&&q.exclusive_options.includes(el.value))this.answers[id]=[el.value];else if(el.checked)this.answers[id]=this.answers[id].filter(v=>!q.exclusive_options.includes(v));}this.dirty++;this.error='';this.missing=this.missing.filter(x=>x!==id);if(['single_choice','multi_choice'].includes(q.type)){this.render();this.shadowRoot.getElementById(el.id)?.focus({preventScroll:true});}this.status();clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush(),500);}
    async action(action,questionId){
      if(this.busy||this.acting||this.accountBusy)return;
      if(action==='confirm-saved'){const q=this.form?.template.questions.find(q=>q.id===questionId);if(q?.reuse_status!=='confirm')return;this.answers[q.id]=structuredClone(q.saved_value);this.dirty++;this.error='';this.missing=this.missing.filter(id=>id!==q.id);this.render();this.status();clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush(),500);return;}
      if(this.busy||this.acting||this.accountBusy)return;this.acting=true;
      try{await this.performAction(action,questionId);}finally{this.acting=false;}
    }
    async performAction(action,questionId){
      if(action==='buy-offer'){
        if(this.offerResults[questionId])return;
        this.busy=true;this.error='';this.render();
        try{this.offerResults[questionId]=await this.api('/offers','POST',{quote_id:questionId,confirmed:true});}
        catch(e){this.offerResults[questionId]={status:'needs_review',message:e.status&&e.status<500?e.message:'We could not confirm the payment result. Check with support before trying again.'};}
        finally{this.busy=false;this.render();}return;
      }
      if(action==='start-intake'){this.started=true;this.render();this.focus();return;}
      if(action==='back-to-order'){if(this.form&&this.form.status!=='submitted'&&!await this.flush()){this.render();return;}this.started=false;this.render();this.shadowRoot.querySelector('.purchase-progress h2')?.scrollIntoView({block:'start'});return;}
      if(action==='refresh-progress'){await this.loadJourneys(true);return;}
      if(action==='select-product'){
        this.started=true;
        const target=Number(questionId);if(!Number.isInteger(target)||target<0||target>=this.orders.length||target===this.index)return;
        if(this.form&&this.form.status!=='submitted'&&!await this.flush()){this.render();return;}
        this.index=target;this.form=null;await this.load();this.focus();return;
      }
      if(action==='identity-verify'){
        const form=this.shadowRoot.querySelector('#identity-form');if(!form?.reportValidity())return;
        let last4=form.querySelector('#identity-last4').value;form.reset();this.busy=true;this.error='';this.render();
        try{await this.api('/identity','POST',{last4});await this.finishIdentity();}catch(e){this.error=e.message;}finally{last4='';this.busy=false;this.render();this.focus();}return;
      }
      if(action==='account-save'){await this.saveAccount();return;}
      if(action==='account-reload'){await this.loadAccount();return;}
      if(action==='reload'){if(this.form&&this.dirty>this.saved&&!await this.flush()){this.render();return;}await this.load();return;}
      if(this.form&&this.form.status!=='submitted'&&!await this.flush()){this.render();return;}
      if(action==='portal'){
        this.busy=true;this.error='';this.render();
        try{if(this.canAutoSignIn()){const url=new URL(`/portal/${encodeURIComponent(this.site)}`,origin);url.hash=new URLSearchParams({handoff:this.handoff}).toString();this.handoff=null;window.location.assign(url.href);return;}const links=await Promise.all(this.orders.map(s=>this.api('/portal','POST',{},s)));const expected=`/portal/${encodeURIComponent(this.site)}`;const urls=links.map(l=>new URL(l.enrollment_url));if(urls.some(u=>u.origin!==origin||u.pathname!==expected))throw new Error('The member portal link could not be verified.');const tokens=urls.map(u=>new URLSearchParams(u.hash.slice(1)).get('invite')).filter(Boolean);const url=new URL(expected,origin);if(tokens.length)url.hash=new URLSearchParams({invites:JSON.stringify(tokens)}).toString();this.portalLink=url.href;window.location.assign(url.href);}catch(e){this.error=e.message;}finally{this.busy=false;this.render();}return;
      }
      if(action==='next-product'){const next=this.orders.findIndex((_,i)=>i!==this.index&&!this.intakeComplete(i));if(next<0)return;this.index=next;this.form=null;await this.load();this.focus();return;}
      const sections=this.form.template.sections,step=this.form.current_step;
      if(action==='next'||action==='submit'){this.missing=this.form.template.questions.filter(q=>this.visible(q)&&q.required&&(action==='submit'||q.section_id===sections[step].id)&&[undefined,null,''].includes(this.answers[q.id])||this.visible(q)&&q.required&&(action==='submit'||q.section_id===sections[step].id)&&Array.isArray(this.answers[q.id])&&!this.answers[q.id].length).map(q=>q.id);if(this.missing.length){this.error='Please complete the highlighted questions.';this.render();this.shadowRoot.querySelector('.error')?.scrollIntoView({block:'center'});return;}}
      this.busy=true;this.error='';
      try{if(action==='submit'){this.form=await this.api('/intake/submit','POST',{revision:this.form.revision});this.rememberIntake();await this.loadJourney(this.index);void this.loadOffers();}else{const direction=action==='back'?-1:1;let next=step+direction;while(next>0&&next<sections.length-1&&!this.form.template.questions.some(q=>q.section_id===sections[next].id&&this.visible(q)))next+=direction;this.form.current_step=Math.max(0,Math.min(sections.length-1,next));this.dirty++;await this.flush();}}catch(e){if(e.detail?.code==='identity_verification_required'){this.identityGate=true;this.error='';}else this.error=e.message;this.missing=e.questions||[];}finally{this.busy=false;this.render();this.focus();}
    }
  }
  if(!customElements.get('wlmd-purchase-intake'))customElements.define('wlmd-purchase-intake',PurchaseIntake);
})();
