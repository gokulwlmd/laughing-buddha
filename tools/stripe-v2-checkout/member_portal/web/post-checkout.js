/* Shared post-purchase intake and Sticky password setup. No provider credentials. */
(() => {
  'use strict';
  const origin = new URL(document.currentScript.src).origin;
  let idComponent;
  const loadIDComponent=()=>idComponent||(idComponent=import(origin+'/portal-assets/id-upload.js'));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function matchesCondition(c,a){if(c.all)return c.all.every(x=>matchesCondition(x,a));if(c.any)return c.any.some(x=>matchesCondition(x,a));const v=a[c.question_id],empty=v==null||v===''||Array.isArray(v)&&!v.length;if(c.operator==='isEmpty')return empty;if(empty)return false;if(c.operator==='isFilled')return true;if(c.operator==='equals')return Array.isArray(v)?v.includes(c.value):v===c.value;if(c.operator==='notEquals')return Array.isArray(v)?!v.includes(c.value):v!==c.value;if(c.operator==='contains')return v.includes(c.value);if(c.operator==='notContains')return !v.includes(c.value);return false;}
  class PurchaseIntake extends HTMLElement {
    constructor() { super(); this.attachShadow({mode:'open'}); this.shadowRoot.addEventListener('pointerdown',e=>{const button=e.target.closest('button[data-action]');if(button&&!button.disabled&&e.button===0){e.preventDefault();}}); this.shadowRoot.addEventListener('input',e=>this.input(e));this.shadowRoot.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action)this.action(action,e.target.closest('[data-action]')?.dataset.q);}); this.shadowRoot.addEventListener('submit',e=>{e.preventDefault();if(e.target.id==='account-form')this.action('account-save');if(e.target.id==='identity-form')this.action('identity-verify');});this.offers={};this.offerResults={};this.orders=[]; this.intakeStates=[]; this.linkedAccounts=new Set(); this.journeys=[]; this.journeyErrors=[]; this.index=0; this.dirty=0; this.saved=0; this.pending=null; this.busy=false; this.error=''; this.missing=[]; this.exit=e=>{if(this.dirty>this.saved){e.preventDefault();e.returnValue='';}}; }
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
    progressPanel(){
      const item=this.journeys[this.index],journey=item?.journey,accountReady=['ready','sign_in'].includes(this.account?.state);
      const complete=this.orders.filter((_,i)=>this.intakeComplete(i)).length;
      return `<section class="panel purchase-progress" aria-label="Purchase and next steps"><p class="meta">YOUR PURCHASE IS CONFIRMED</p><h2>Thank you. Your payment is confirmed.</h2><p>${esc((item?.product_name||'Your treatment').replace(/ \/ /g,' · ').replace('1 months','1 month'))}${item?` · Order ${esc(item.id)}`:''}</p><p class="next-copy">${complete===this.orders.length?'Your intake is saved. Open your care plan for the next steps.':'Next, complete your health intake so your care team has the information needed to review your treatment.'}</p><button data-action="start-intake" ${this.busy?'disabled':''}>${complete===this.orders.length?'See my next steps':this.form?.current_step?'Continue health intake':'Complete health intake'}</button><ol class="setup-steps" aria-label="After-purchase checklist"><li><strong>${accountReady?'✓':'1'} Account</strong><small>${accountReady?'Ready':'Set password'}</small></li><li><strong>${complete===this.orders.length?'✓':'2'} Health intake</strong><small>${complete} of ${this.orders.length} complete</small></li><li><strong>${complete===this.orders.length?'✓':'3'} Identity</strong><small>${complete===this.orders.length?'Complete':'Final step'}</small></li></ol>${this.orders.length>1?`<nav class="products" aria-label="Purchased products">${this.orders.map((_,i)=>`<button class="secondary" data-action="select-product" data-q="${i}" ${i===this.index?'aria-current="true"':''} ${this.busy?'disabled':''}>${esc(this.journeys[i]?.product_name||`Product ${i+1}`)}<small>${this.intakeComplete(i)?'Complete':this.intakeStates[i]||this.journeys[i]?'Intake needed':'Open intake'}</small></button>`).join('')}</nav>`:''}${journey?`<details class="progress-details"><summary>See order progress</summary><p>${esc(journey.title)}</p><ol>${journey.stages.map(stage=>`<li><strong>${esc(stage.label)}</strong> — ${esc(stage.detail)}</li>`).join('')}</ol>${journey.tracking_number?`<p>Tracking number: <strong>${esc(journey.tracking_number)}</strong></p>`:''}<button class="secondary" data-action="refresh-progress">Refresh order updates</button></details>`:''}</section>`;
    }
    async loadAccount(){
      try{this.account=await this.api('/account','GET',undefined,this.orders[0]);}catch(e){this.accountError='Your purchase is saved. Portal password setup is temporarily unavailable.';}finally{this.render();}
    }
    accountPanel(){
      if(!this.account&&!this.accountError)return '';
      const state=this.account?.state;
      if(state==='ready')return `<section class="account-ready"><h2>Your portal password is saved</h2><p>${this.canAutoSignIn()?'Finish your intake, then open your care plan without signing in again.':'Finish your intake, then use your password to open your member portal.'}</p></section>`;
      if(state==='sign_in')return '<div class="account-ready">✓ Your existing member account is ready. Finish your intake below.</div>';
      if(state==='needs_review'||!state)return `<section class="panel account"><h2>Your member portal</h2><p role="status">${esc(this.accountError||'Your purchase is saved. Contact support to finish account setup.')}</p><button class="secondary" data-action="account-reload">Check account setup</button><button class="secondary" data-action="portal">Open member portal</button></section>`;
      return `<section class="panel account"><h2>Set your member portal password</h2><p>${this.linkedAccounts.size?'Your password is saved. Enter the same password to finish connecting the remaining products.':'Track your orders, manage deliveries and finish your intake later. No email step needed.'}</p>${this.accountError?`<p class="error" role="alert">${esc(this.accountError)}</p>`:''}<form id="account-form"><label for="new-password">Choose a password</label><input id="new-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required aria-describedby="password-help"><p id="password-help" class="meta">Use at least 12 characters.</p><label for="confirm-password">Confirm password</label><input id="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required><div class="actions"><button type="submit" ${this.accountBusy?'disabled':''}>${this.accountBusy?'Saving password…':'Save portal password'}</button></div></form></section>`;
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
        this.account={...this.account,state:'ready'};void this.loadOffers(true);
      }catch(e){this.accountError=e.message;}
      finally{password='';this.accountBusy=false;this.render();}
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
      if(q.reuse_status==='stable'&&!editing)return `<fieldset><legend>${esc(q.label)}</legend><p>${esc(this.answers[q.id])} · ${q.prefill_source==='checkout'?'From your checkout':'Saved from your previous intake'}</p><details><summary>Change saved answer</summary>${this.field(q,true)}</details></fieldset>`;
      const previous=q.reuse_status==='confirm'?`<p>Previously: ${esc(q.saved_value)}</p><p>Confirm this is still correct, or enter an updated answer below.</p><button type="button" class="secondary" data-action="confirm-saved" data-q="${esc(q.id)}">Still correct</button>`:'';
      const value=this.answers[q.id],id=`q-${q.id}`;let input;
      if(q.type==='single_choice'&&(q.presentation==='select'||q.options.length>6))input=`<select aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}"><option value="">Select an option</option>${q.options.map(o=>`<option value="${esc(o.value)}" ${value===o.value?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`;
      else if(q.type==='single_choice'||q.type==='multi_choice')input=q.options.map((o,i)=>`<label class="choice"><input id="${esc(id+'-'+i)}" data-q="${esc(q.id)}" type="${q.type==='single_choice'?'radio':'checkbox'}" name="${esc(q.id)}" value="${esc(o.value)}" ${(q.type==='single_choice'?value===o.value:Array.isArray(value)&&value.includes(o.value))?'checked':''}>${esc(o.label)}</label>`).join('');
      else input=q.type==='textarea'?`<textarea aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" rows="3" maxlength="1000">${esc(value)}</textarea>`:`<input aria-label="${esc(q.label)}" id="${esc(id)}" data-q="${esc(q.id)}" type="${q.type==='number'?'number':['email','tel','date'].includes(q.input_type)?q.input_type:'text'}" ${q.type==='number'?'step="any"':'maxlength="1000"'} value="${esc(value)}">`;
      return `<fieldset><legend>${esc(q.label)} ${q.required?'':'<small>(optional)</small>'}</legend>${q.hint?`<p class="meta">${esc(q.hint)}</p>`:''}${previous}${input}${this.missing.includes(q.id)?'<p class="error">Please answer this question.</p>':''}</fieldset>`;
    }
    render(){
      const active=this.shadowRoot.activeElement,activeId=active?.id;
      const ephemeral={};
      if(!this.accountBusy)for(const id of ['new-password','confirm-password','identity-last4']){const node=this.shadowRoot.getElementById(id);if(node)ephemeral[id]=node.value;}
      const f=this.form,sections=f?.template.sections||[],step=f?.current_step||0,section=sections[step],visibleSteps=sections.map((s,i)=>({s,i})).filter(({s,i})=>i===sections.length-1||f.template.questions.some(q=>q.section_id===s.id&&this.visible(q)));const displayStep=Math.max(1,visibleSteps.findIndex(x=>x.i===step)+1);
      this.shadowRoot.innerHTML=`<style>:host{display:block;scroll-margin-top:110px;color:inherit;font:inherit}*{box-sizing:border-box}.account-ready{max-width:820px;margin:16px auto 24px;padding:16px 20px;background:#eef5ee;border-radius:12px;font-size:15px;line-height:1.5}.account-ready h2{font-size:17px;margin:0}.account-ready p{margin:5px 0 0}.setup-steps small{display:block;margin-top:5px;font-size:12px}.offer-panel{margin-top:24px!important;margin-bottom:24px!important}.offer-card{border-top:1px solid #dedbd5;padding:20px 0}.offer-card h3{font-size:21px;margin:0}.next-steps{padding:0;list-style:none;display:grid;gap:20px;margin:28px 0}.next-steps li{border-left:3px solid var(--intake-accent,#245844);padding-left:16px}.next-steps span{display:block;color:#62625c;line-height:1.6;margin-top:5px}.choice:has(input:checked){border-color:var(--intake-accent,#245844);background:#f4f8f5}.panel[aria-busy]{scroll-margin-top:24px}.account,.purchase-progress{margin-bottom:24px!important}.setup-steps{list-style:none;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.setup-steps li{background:#f6f5f1;padding:14px;border-radius:12px;font-size:14px;line-height:1.5}@media(max-width:600px){.setup-steps{gap:6px}.setup-steps li{padding:10px 8px;font-size:12px}.setup-steps strong{display:block}.actions button{flex:1}.panel{border-radius:16px}button{width:auto}.portal a{display:none}}.products{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:20px 0}.products button{text-align:left}.products small{display:block;margin-top:6px;font-weight:400}.products [aria-current]{outline:2px solid var(--intake-accent,#245844)}.progress-details{margin:20px 0}.progress-details summary{cursor:pointer;padding:12px 0;font-weight:600}.progress-details li{margin:12px 0;line-height:1.5}.purchase-progress>button{margin-top:12px}.account label{display:block;margin:16px 0 8px;font-weight:600}.panel{max-width:820px;margin:0 auto;border:1px solid #dedbd5;background:#fff;border-radius:20px;padding:clamp(20px,4vw,40px)}h2{font-size:clamp(24px,4vw,32px);line-height:1.25;margin:12px 0}p{line-height:1.6}.meta,small{color:#62625c}fieldset{border:0;padding:0;margin:26px 0}legend{font-weight:600;font-size:18px;line-height:1.5;margin-bottom:12px}input:not([type=radio]):not([type=checkbox]),textarea{width:100%;font:inherit;font-size:17px;border:1px solid #aaa;border-radius:8px;padding:13px;background:#fff;color:#222}input[type=radio],input[type=checkbox]{width:21px;height:21px;flex:none;accent-color:var(--intake-accent,#245844)}.choice{display:flex;gap:12px;align-items:center;min-height:52px;border:1px solid #ddd;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}button,a{font:inherit;font-weight:600;font-size:16px;min-height:48px;border-radius:8px;padding:12px 18px;cursor:pointer}button{background:var(--intake-accent,#245844);color:white;border:0}button.secondary{background:#f1f0eb;color:#222}button:disabled{opacity:.6;cursor:wait}.actions{display:flex;gap:12px;flex-wrap:wrap;justify-content:space-between;margin-top:28px}.error{color:#a52822}.save{min-height:24px;font-size:14px}a{color:inherit;display:inline-flex;align-items:center}progress{width:100%;height:8px;accent-color:var(--intake-accent,#245844)}:focus-visible{outline:3px solid #245844;outline-offset:3px}.portal{border-top:1px solid #ddd;margin-top:28px;padding-top:20px}.purchase-progress{padding:24px!important}.purchase-progress h2{font-size:26px}.purchase-progress>p{margin:8px 0}.purchase-progress .next-copy{color:#62625c}.purchase-progress .setup-steps{margin:20px 0 0}.progress-details{margin:8px 0 0}.account h2{font-size:24px}.account p{margin:8px 0}.panel select{width:100%;font:inherit;font-size:17px;border:1px solid #aaa;border-radius:8px;padding:13px;background:#fff;color:#222;min-height:52px}.panel fieldset:has(details){margin:16px 0;padding:14px 16px;background:#f7f6f2;border-radius:10px}.panel fieldset:has(details) p{margin:4px 0}.panel details summary{cursor:pointer;min-height:32px;font-size:15px}.panel[aria-busy] h2{font-size:28px}.panel[aria-busy]{max-width:720px}@media(max-width:600px){.purchase-progress h2{font-size:23px}.purchase-progress>button{width:100%}.panel{padding:20px}.panel[aria-busy]{scroll-margin-top:12px}}</style>${this.progressPanel()}${this.accountPanel()}${this.offersPanel('thank_you')}${this.offersPanel('before_intake')}<section class="panel" aria-busy="${this.busy}"><p class="meta">Health intake${this.orders.length>1?` · Product ${this.index+1} of ${this.orders.length}`:''}</p><h2 tabindex="-1">${esc(this.identityGate?'One last step: verify your identity':f?.status==='submitted'?'Your intake is saved':section?.title||f?.template.title||'Your next step')}</h2>${this.error?`<p class="error" role="alert">${esc(this.error)}</p>`:''}${this.identityGate?`<p>Your health answers are saved. Choose a photo of your ID or the last four digits of your SSN to finish your intake.</p><form id="identity-form"><label for="identity-last4">Last 4 digits of your SSN</label><input id="identity-last4" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="off" required aria-describedby="identity-privacy" style="display:block;max-width:220px;letter-spacing:.35em;font-size:24px;margin-top:12px"><p id="identity-privacy" class="meta">We don’t store your SSN digits.</p><button type="submit" ${this.busy?'disabled':''}>${this.busy?'Verifying…':'Verify & finish intake'}</button></form><wlmd-id-upload intake></wlmd-id-upload>`:!f?`<p>${this.busy?'Opening your intake…':'Your order is saved. Please try opening your intake again.'}</p><button data-action="reload" ${this.busy?'disabled':''}>Try again</button>`:f.status==='submitted'?`<p>Your intake has been submitted. Your answers are saved with this order.</p><ol class="next-steps"><li><strong>Check your care plan</strong><span>See this order’s status and any remaining tasks in your member portal.</span></li><li><strong>Follow your delivery</strong><span>Your tracking link appears when the order ships.</span></li><li><strong>Manage your next supply</strong><span>Your treatment shows your refill date and what is included.</span></li></ol>${this.orders.some((_,i)=>i!==this.index&&!this.intakeComplete(i))?'<button data-action="next-product">Finish another product’s intake</button>':'<button data-action="portal">Go to my care plan →</button>'}`:`<p class="meta">Step ${displayStep} of ${visibleSteps.length} · ${esc(section?.title)}</p><progress aria-label="Health intake progress" value="${displayStep}" max="${visibleSteps.length}"></progress><p>${esc(section?.description)}</p><form novalidate>${f.template.questions.filter(q=>q.section_id===section?.id&&this.visible(q)).map(q=>this.field(q)).join('')}<p class="save" data-save aria-live="polite"></p><div class="actions">${step?'<button type="button" class="secondary" data-action="back">Back</button>':'<span></span>'}<button type="button" data-action="${step===sections.length-1?'submit':'next'}" ${this.busy?'disabled':''}>${this.busy?'Saving…':step===sections.length-1?'Submit intake':'Continue'}</button></div></form>`}<div class="portal"><p>Your progress is saved as you go. You can also finish in your member portal.</p><button class="secondary" data-action="portal" ${this.busy?'disabled':''}>Open member portal</button>${this.portalLink?`<p><a href="${esc(this.portalLink)}">Continue to member portal →</a></p>`:''}</div></section>${this.offersPanel('after_intake')}`;
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
      if(action==='start-intake'){this.focus();return;}
      if(action==='refresh-progress'){await this.loadJourneys(true);return;}
      if(action==='select-product'){
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
