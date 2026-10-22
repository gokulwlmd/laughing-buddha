(() => {
  'use strict';
  const STORAGE_KEY = 'patient-portal-demo-workspace-v1';
  const icons = {
    leaf: '<path d="M19 4c-7-1-13 2-13 8a6 6 0 0 0 6 6c6 0 8-7 7-14Z"/><path d="M5 21 15 10M10 15v-5m0 5h5"/>',
    home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
    box: '<path d="m3 7 9-4 9 4v10l-9 4-9-4Z"/><path d="m3 7 9 4 9-4M12 11v10M7 5l10 5"/>',
    clipboard: '<path d="M9 4H6a2 2 0 0 0-2 2v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V6a2 2 0 0 0-2-2h-3"/><rect x="9" y="2" width="6" height="5" rx="1"/><path d="m8 13 2 2 5-5M8 18h8"/>',
    chat: '<path d="M21 11a8 8 0 0 1-8 8H7l-4 3V5a2 2 0 0 1 2-2h8a8 8 0 0 1 8 8Z"/><path d="M7 8h9M7 12h6"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8Z"/><path d="M14 3v5h5M9 12h6M9 16h6"/>',
    people: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v3"/>',
    link: '<path d="M14 3h7v7M21 3 11 13M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>',
    shield: '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>',
    bottle: '<path d="M9 3h6v4l3 4v9a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-9l3-4Z"/><path d="M9 7h6M6 13h12M6 18h12M8 3h8"/>',
    send: '<path d="m22 2-7 20-4-9L2 9Z"/><path d="m22 2-11 11"/>',
  };
  const icon = (name, size = 19) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const money = order => new Intl.NumberFormat('en-US', {style:'currency', currency:order.currency || 'USD', maximumFractionDigits:2}).format(Number(order.total || 0));
  const date = value => value ? new Date(value).toLocaleDateString('en-US', {month:'short', day:'numeric'}) : 'Just now';
  const textStatus = value => ({draft:'In progress', not_started:'Not started', not_submitted:'Not submitted', awaiting_review:'Awaiting review', submitted:'Submitted', paid_demo:'Paid · demo', complete:'Complete'}[value] || String(value || 'Not started').replace(/_/g, ' '));
  const state = {workspace:null, site:null, config:null, patient:null, role:location.pathname.startsWith('/admin-demo/')?'admin':'patient', view:'dashboard', therapy:'', orders:[], overview:null, messages:[], intake:null, orderId:null, loading:false, error:'', dirtyVersion:0, savedVersion:0, saveError:'', saving:false, fieldsError:{}, messageDraft:'', messageId:null, sending:false};
  let autosaveTimer = null;
  let savePromise = null;
  let generation = 0;
  const root = document.getElementById('app');
  const announce = text => { document.getElementById('announcer').textContent = text; };
  const token = (role = state.role, site = state.site) => role === 'admin' ? site.admin_token : site.patient_token;
  async function request(path, options = {}, role = state.role, site = state.site) {
    const headers = {'Content-Type':'application/json', ...(site ? {'Authorization':`Bearer ${token(role, site)}`} : {})};
    const response = await fetch(path, {...options, headers:{...headers, ...options.headers}});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : payload.detail?.message;
      const error = new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || detail || payload.message || 'Please check your answers and try again. Your unsaved changes are still here.');
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  const endpoint = (suffix, site = state.site) => `/api/v1/sites/${encodeURIComponent(site.id)}${suffix}`;
  const therapyQuery = () => state.therapy ? `?therapy_id=${encodeURIComponent(state.therapy)}` : '';
  const selectedOrders = () => state.orders.filter(order => !state.therapy || order.therapy_id === state.therapy);
  const pendingOrders = () => selectedOrders().filter(order => order.intake_status !== 'submitted');
  const notice = (message, type = '') => message ? `<div class="notice ${type}" role="${type === 'error' ? 'alert' : 'status'}">${esc(message)}</div>` : '';
  const status = (label, type = 'neutral') => `<span class="status ${type}">${esc(label)}</span>`;
  const intakeStatus = order => order.intake_status === 'submitted' ? status('Intake submitted','good') : status(order.intake_status === 'draft' ? 'Intake in progress' : 'Intake needed','pending');
  const button = (label, action, cls='btn-primary', data='', iconName='') => `<button type="button" class="btn ${cls}" data-action="${action}" ${data}>${esc(label)}${iconName ? icon(iconName,16) : ''}</button>`;
  function pageHead(eyebrow, title, description, filter = false) {
    return `<header class="page-head"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${filter ? therapyFilter() : '<span class="demo-tag">SAMPLE ACCOUNT</span>'}</header>`;
  }
  function therapyFilter() {
    return `<div class="head-filter"><label for="therapy-filter">Therapy</label><select id="therapy-filter"><option value="">All therapies</option>${(state.config?.therapies || []).map(therapy => `<option value="${esc(therapy.id)}" ${state.therapy===therapy.id?'selected':''}>${esc(therapy.name)}</option>`).join('')}</select></div>`;
  }
  function empty(title, description, iconName = 'box') {
    return `<div class="empty">${icon(iconName,30)}<h3>${esc(title)}</h3><p>${esc(description)}</p></div>`;
  }
  function brandStyle() {
    const color = state.config?.site?.color || state.site?.color || '#235c4d';
    const safeColor = /^#[0-9a-f]{6}$/i.test(color) ? color : '#235c4d';
    document.documentElement.style.setProperty('--brand', safeColor);
    document.documentElement.style.setProperty('--soft', `${safeColor}0c`);
  }
  function render() {
    if (!state.site) return;
    brandStyle();
    const admin = state.role === 'admin';
    const navigation = admin ? [['dashboard','home','Overview'],['orders','box','Orders'],['intakes','clipboard','Intake queue'],['leads','people','Partial leads']] : [['dashboard','home','Overview'],['orders','box','My orders'],['intake','clipboard','Medical intake'],['messages','chat','Messages']];
    const siteName = state.config?.site?.name || state.site.name;
    const initials = (state.patient?.name || 'Sample Patient').split(' ').map(part=>part[0]).slice(0,2).join('');
    document.title = `${siteName} · ${admin ? 'Admin demo' : 'Patient portal demo'}`;
    root.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-mark">${icon('leaf',25)}</span><div><div class="brand-name">${esc(siteName)}</div><div class="brand-caption">${admin?'Site administration':'Your patient portal'}</div></div></div><nav aria-label="${admin?'Admin':'Patient'} navigation"><div class="nav-heading">${admin?'Manage this site':'Your care, together'}</div><div class="nav-list">${navigation.map(([view, symbol, label])=>`<button class="nav-link ${state.view===view?'active':''}" data-action="navigate" data-view="${view}" ${state.view===view?'aria-current="page"':''}>${icon(symbol)}<span>${label}</span>${view==='intake' && pendingOrders().length?'<span class="nav-dot"></span>':''}</button>`).join('')}</div></nav><div class="sidebar-bottom">${icon('shield',20)}<p>Separate branding and sample records for every site.</p><a class="subtle-link" href="/sites/${encodeURIComponent(state.site.id)}/docs" target="_blank" rel="noopener">Explore this site's API ${icon('link',12)}</a></div></aside><div class="app-body"><header class="topbar"><div class="site-control"><label for="site-select">Demo site</label><select id="site-select">${state.workspace.sites.map(site=>`<option value="${esc(site.id)}" ${site.id===state.site.id?'selected':''}>${esc(site.name)}</option>`).join('')}</select></div><div class="top-actions"><div class="persona-switch" role="group" aria-label="Demo perspective"><button class="${!admin?'active':''}" data-action="persona" data-role="patient" aria-pressed="${!admin}">Patient</button><button class="${admin?'active':''}" data-action="persona" data-role="admin" aria-pressed="${admin}">Admin</button></div><span class="avatar" aria-label="Sample account">${admin?'AD':esc(initials)}</span></div></header><main class="main" id="main-content">${state.error?notice(state.error,'error'):''}${state.loading?'<div class="card loading-card" role="status"><span class="loader" aria-label="Loading"></span></div>':admin?renderAdmin():renderPatient()}<div class="bottom-note">${icon('shield',12)}<span>Demo workspace · sample information · records stay separate by site</span></div></main></div></div>`;
  }
  function stat(value, label, symbol) { return `<div class="card stat"><span class="stat-icon">${icon(symbol,19)}</span><div><div class="stat-value">${esc(value)}</div><div class="stat-label">${esc(label)}</div></div></div>`; }
  function compactOrder(order) {
    return `<div class="order-row"><div class="product-icon">${icon('bottle',25)}</div><div class="order-detail"><h3>${esc(order.product_name)}</h3><div class="order-meta">${esc(order.plan_name)}<br>${esc(order.number)} · ${date(order.created_at)}</div>${intakeStatus(order)}</div><div class="order-side"><span class="order-price">${money(order)}</span><button class="text-button" data-action="open-intake" data-order="${esc(order.id)}">${order.intake_status==='submitted'?'View intake':'Complete intake'}</button></div></div>`;
  }
  function renderPatient() {
    if (state.view === 'orders') return pageHead('Your purchases','My orders','See each order, its medical intake and what happens next.',true) + `<div class="list-orders">${selectedOrders().map(fullOrder).join('') || `<div class="card">${empty('No orders for this therapy','Choose another therapy to see your sample orders.')}</div>`}</div>`;
    if (state.view === 'intake') return renderIntake();
    if (state.view === 'messages') return renderMessages();
    const firstName = (state.patient?.name || 'Alex').split(' ')[0];
    const next = pendingOrders()[0];
    return pageHead('Your health, in one place',`Welcome back, ${firstName}.`,'Everything you need to follow your orders and take your next step.') +
      `<div class="summary-grid">${stat(state.orders.length,'Sample orders','box')}${stat(pendingOrders().length,'Intakes to complete','clipboard')}${stat(state.orders.filter(order=>order.intake_status==='submitted').length,'Awaiting review','clock')}</div><div class="grid-main"><div class="stack"><section class="card welcome-card"><div class="eyebrow">${next?'Your next step':'You’re up to date'}</div><h2>${next?'A little about you. A better starting point.':'Your intake is ready for the next step.'}</h2><p>${next?'Complete your sample medical intake for '+esc(next.product_name)+'. Your progress saves as you go, so you can come back anytime.':'Your sample answers have been submitted. This demo does not send them to a medical team or approve treatment.'}</p>${next?button(next.intake_status==='draft'?'Continue your intake':'Start medical intake','open-intake','btn-light',`data-order="${esc(next.id)}"`,'arrow'):button('View your orders','navigate','btn-light','data-view="orders"','arrow')}</section><section class="card card-pad"><div class="card-heading"><h2>Recent orders</h2><button class="text-button" data-action="navigate" data-view="orders">View all orders</button></div>${state.orders.slice(0,3).map(compactOrder).join('') || empty('No orders yet','Sample orders will appear here.')}<div class="order-footer"><p class="small-note">Payment, medical review and delivery<br>are tracked separately.</p>${status('Demo payments only','neutral')}</div></section></div><div class="stack"><section class="card card-pad"><div class="card-heading"><h2>What happens next?</h2></div><div class="task-item"><span class="task-number ${!next?'done':''}">${!next?icon('check',14):'1'}</span><div><h3>Tell us about your health</h3><p>Answer the questions for your chosen therapy. Save and return when it suits you.</p></div></div><div class="task-item"><span class="task-number">2</span><div><h3>Medical review</h3><p>In the connected experience, your medical team reviews your submitted answers.</p></div></div><div class="task-item"><span class="task-number">3</span><div><h3>Follow your next steps</h3><p>Find updates about your order and care in your portal.</p></div></div></section><section class="card card-pad helper-card"><div class="helper-icon">${icon('chat',20)}</div><h3>A place to stay in touch</h3><p>Try the messaging experience with a sample message and an automated demo response.</p><button class="text-button" data-action="navigate" data-view="messages">Explore messages ${icon('arrow',13)}</button></section></div></div>`;
  }
  function fullOrder(order) {
    return `<article class="card full-order"><div class="order-head"><div class="product-icon">${icon('bottle',25)}</div><div class="order-detail"><div class="order-id">${esc(order.number)} · ${date(order.created_at)}</div><h3>${esc(order.product_name)}</h3><div class="order-meta">${esc(order.therapy_name)} · ${esc(order.plan_name)}</div></div><div class="order-side"><span class="order-price">${money(order)}</span>${status('Sample order')}</div></div><div class="order-stages"><div class="order-stage"><span>Payment</span><strong>Paid · demo</strong></div><div class="order-stage"><span>Medical intake</span><strong>${esc(textStatus(order.intake_status))}</strong></div><div class="order-stage"><span>Medical review</span><strong>${esc(textStatus(order.medical_status))}</strong></div><div class="order-stage"><span>Delivery</span><strong>${esc(textStatus(order.fulfillment_status))}</strong></div></div><div class="order-actions"><p class="small-note">${order.intake_status==='submitted'?'Sample intake submitted. Medical review and fulfillment are not connected in this demo.':'Complete the intake for this order. A sample payment does not mean treatment is approved.'}</p>${button(order.intake_status==='submitted'?'View submitted intake':'Complete intake','open-intake','btn-secondary btn-small',`data-order="${esc(order.id)}"`,'arrow')}</div></article>`;
  }
  function visibleQuestions(intake = state.intake) {
    return (intake?.template?.questions || []).filter(question => !question.show_if || intake.answers?.[question.show_if.question_id] === question.show_if.equals);
  }
  const answered = (question, answers = state.intake?.answers || {}) => {
    const value = answers[question.id];
    return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== null && String(value).trim() !== '';
  };
  function progress() {
    const questions = visibleQuestions();
    const count = questions.filter(question=>answered(question)).length;
    return {count, total:questions.length, percent:questions.length ? Math.round(count/questions.length*100) : 0};
  }
  function savedMarkup() {
    if (state.intake?.status==='submitted') return `${icon('check',12)} Submitted`;
    if (state.saveError) return `${icon('clock',12)} Not saved <button data-action="retry-save">Retry</button>`;
    if (state.saving || state.dirtyVersion > state.savedVersion) return `${icon('clock',12)} Saving…`;
    return `${icon('check',12)} ${state.intake?.updated_at ? 'Saved' : 'Ready to start'}`;
  }
  function renderIntake() {
    const intake = state.intake;
    if (!intake) return pageHead('A few questions about you','Medical intake','Choose an order to begin or continue your sample intake.') + `<div class="card card-pad">${state.orders.map(compactOrder).join('') || empty('No intake available','An intake will be attached to each sample order.','clipboard')}</div>`;
    const order = state.orders.find(item=>item.id === state.orderId);
    const sections = intake.template.sections || [];
    const step = Math.max(0, Math.min(Number(intake.current_step)||0,sections.length-1));
    const section = sections[step];
    const completion = progress();
    const head = pageHead(order?.therapy_name || 'Medical intake',intake.status === 'submitted' ? 'Your submitted intake' : 'Let’s get to know you.',`${order?.product_name || 'Your therapy'}${order?.plan_name ? ' · '+order.plan_name : ''}`);
    if (intake.status === 'submitted') return head + `<section class="card submitted-hero"><div class="submitted-icon">${icon('check',27)}</div><h2>Sample intake submitted</h2><p>Your answers are saved and this intake is now read-only. No medical review or treatment approval takes place in this demo.</p>${status('Awaiting review · demo','blue')}<div style="margin-top:20px">${button('Back to my orders','navigate','btn-secondary','data-view="orders"')}</div><dl class="answer-list">${visibleQuestions().map(question=>`<div class="answer-row"><dt>${esc(question.label)}</dt><dd>${esc(answerLabel(question, intake.answers[question.id]))}</dd></div>`).join('')}</dl></section>`;
    return head + notice('These are sample questions for this therapy, not a clinical assessment. Please use the sample answers provided.') + `<div class="intake-layout"><section class="card intake-card"><div class="intake-toolbar"><span class="step-label">STEP ${step+1} OF ${sections.length}</span><span class="saved-state ${state.saveError?'error':''}" id="save-status" aria-live="polite">${savedMarkup()}</span></div><div class="mobile-sample" style="display:none"><button class="text-button" data-action="sample-answers">Fill this intake with sample answers</button></div><h2>${esc(section?.title || intake.template.title)}</h2><p class="section-description">${esc(section?.description || intake.template.description || 'Your progress saves automatically as you answer.')}</p><div id="intake-error">${notice(state.saveError,'error')}</div><form id="intake-form" novalidate>${step===sections.length-1 ? reviewAnswers(section?.id) : ''}${visibleQuestions().filter(question=>question.section_id===section?.id).map(questionField).join('')}<div class="intake-actions">${step>0?button('Back','intake-back','btn-secondary'):button('My orders','navigate','btn-secondary','data-view="orders"')}<div class="intake-actions-right">${step===sections.length-1?button('Submit sample intake','submit-intake','btn-primary','','check'):button('Save & continue','intake-next','btn-primary','','arrow')}</div></div></form></section><aside class="intake-side"><section class="card card-pad"><div class="eyebrow">Your intake</div><h3>${esc(intake.template.title)}</h3><p class="small-note" style="margin-top:8px">Go at your own pace. Your progress stays with this order.</p><div class="progress-copy"><span id="progress-count">${completion.count} of ${completion.total} answered</span><strong id="progress-percent">${completion.percent}%</strong></div><div class="progress-track"><div class="progress-fill" id="progress-fill" style="width:${completion.percent}%"></div></div><nav class="section-nav" aria-label="Intake sections">${sections.map((item,index)=>`<button class="section-link ${index===step?'active':''} ${index<step?'complete':''}" data-action="intake-section" data-step="${index}" ${index===step?'aria-current="step"':''}><span class="section-number">${index<step?icon('check',12):index+1}</span>${esc(item.title)}</button>`).join('')}</nav><div class="sample-action"><div><p>Exploring the demo? Use fictional answers to try the complete journey.</p><button class="text-button" data-action="sample-answers">Fill sample answers ${icon('arrow',12)}</button></div></div></section></aside></div>`;
  }
  function reviewAnswers(currentSection) {
    return `<section class="review-box"><div class="card-heading"><h3>Your answers so far</h3><button type="button" class="text-button" data-action="intake-section" data-step="0">Edit answers</button></div><dl>${visibleQuestions().filter(question=>question.section_id!==currentSection).map(question=>`<div class="answer-row"><dt>${esc(question.label)}</dt><dd>${esc(answerLabel(question,state.intake.answers[question.id]))}</dd></div>`).join('')}</dl></section>`;
  }
  function answerLabel(question, value) {
    const label = val => (question.options || []).find(option=>option.value===val)?.label || val;
    return Array.isArray(value) ? value.map(label).join(', ') : value===undefined || value==='' ? 'Not answered' : label(value);
  }
  function questionField(question) {
    const value = state.intake.answers?.[question.id];
    const qid = esc(question.id);
    const id = `question-${qid}`;
    const label = `${esc(question.label)}${question.required?'<span class="required" aria-label="required">*</span>':''}`;
    const hint = question.hint ? `<p class="field-hint" id="hint-${qid}">${esc(question.hint)}</p>` : '';
    const description = question.hint ? `aria-describedby="hint-${qid}"` : '';
    const error = state.fieldsError[question.id] ? `<p class="field-error" role="alert">${esc(state.fieldsError[question.id])}</p>` : '';
    if (question.type==='single_choice' || question.type==='multi_choice') return `<div class="field"><fieldset><legend>${label}</legend>${hint}<div class="choices">${(question.options || []).map((option,index)=>`<label class="choice" for="${id}-${index}"><input id="${id}-${index}" data-question="${qid}" name="${qid}" type="${question.type==='multi_choice'?'checkbox':'radio'}" value="${esc(option.value)}" ${question.type==='multi_choice'?(Array.isArray(value)&&value.includes(option.value)?'checked':''):(value===option.value?'checked':'')} ${description}><span>${esc(option.label)}</span></label>`).join('')}</div>${error}</fieldset></div>`;
    return `<div class="field"><label for="${id}">${label}</label>${hint}${question.type==='textarea'?`<textarea id="${id}" data-question="${qid}" ${description} maxlength="1000">${esc(value)}</textarea>`:`<input id="${id}" data-question="${qid}" type="${question.type==='number'?'number':'text'}" value="${esc(value)}" ${question.type==='number'?'step="any"':'maxlength="500"'} ${description} ${question.required?'aria-required="true"':''}>`}${error}</div>`;
  }
  function renderMessages() {
    return pageHead('A conversation, in one place','Messages','Try a sample conversation for this site. Your clinical messaging API will connect here.') + `<div class="message-layout"><section class="card"><div class="message-header"><span class="stat-icon">${icon('chat',19)}</span><div><h2>Your care conversation</h2><p>Demo assistant · automated sample replies</p></div></div><div class="message-list" id="message-list">${state.messages.length ? state.messages.map(message=>`<article class="message ${message.sender==='patient'?'patient':''}"><div class="message-name">${message.sender==='patient'?'You · sample patient':'Demo assistant'}</div><div class="bubble">${esc(message.body)}</div><div class="message-date">${date(message.created_at)}</div></article>`).join('') : empty('Start a sample conversation','Send a sample message below to preview how the experience will work.','chat')}</div><form id="message-form" class="message-compose"><label for="message-body">Your sample message</label><textarea id="message-body" ${state.sending?'disabled':''} maxlength="2000" placeholder="For example: Where can I check my intake status?" required>${esc(state.messageDraft)}</textarea><div class="compose-footer"><p class="small-note">No doctor is monitoring this demo.<br>Use fictional information only.</p><button type="submit" class="btn btn-primary" ${state.sending?'disabled':''}>${state.sending?'Sending…':'Send message'} ${icon('send',14)}</button></div></form></section><aside class="card card-pad"><div class="eyebrow">About this preview</div><h3>A familiar place to ask</h3><p class="small-note" style="margin-top:12px">The portal keeps the conversation alongside your orders and intake. For now, responses are clearly marked automated samples.</p><div class="notice" style="margin-top:20px;margin-bottom:0">This demo does not provide medical advice or urgent support.</div></aside></div>`;
  }
  function renderAdmin() {
    const overview = state.overview || {};
    const orders = overview.orders || [];
    const intakes = overview.intakes || [];
    const leads = overview.leads || [];
    if (state.view === 'orders') return pageHead('Site administration','Orders','Track payments, intake, review and delivery separately for this site.',true) + adminOrders(orders);
    if (state.view === 'intakes') return pageHead('Site administration','Intake queue','See which sample patients have started or submitted their therapy intake.',true) + adminIntakes(intakes);
    if (state.view === 'leads') return pageHead('Site administration','Partial leads','Follow sample funnel progress without exposing medical answers.',true) + adminLeads(leads);
    return pageHead('Site administration','A clear view of your site.','Orders, medical intake and incomplete journeys, organized by therapy.',true) + `<div class="summary-grid">${stat(orders.length,'Sample orders','box')}${stat(intakes.filter(item=>item.status==='submitted').length,'Submitted intakes','clipboard')}${stat(leads.length,'Partial leads','people')}</div><div class="stack">${adminOrders(orders)}<div class="grid-main admin-overview-grid"><section class="card card-pad"><div class="card-heading"><h2>Intake progress</h2><button class="text-button" data-action="navigate" data-view="intakes">Open queue</button></div>${intakes.slice(0,3).map(item=>`<div class="order-row"><span class="stat-icon">${icon('clipboard',17)}</span><div class="order-detail"><h3>${esc(item.patient_name || 'Sample patient')}</h3><p class="order-meta">${esc(item.therapy_name)}</p>${status(textStatus(item.status),item.status==='submitted'?'good':'pending')}</div><span class="small-note">${esc(item.answered || 0)}/${esc(item.total || 0)} answers</span></div>`).join('') || empty('No intake yet','Sample intake progress will appear here.','clipboard')}</section><section class="card card-pad"><div class="card-heading"><h2>Incomplete journeys</h2><button class="text-button" data-action="navigate" data-view="leads">View leads</button></div>${leads.slice(0,3).map(item=>`<div class="order-row"><span class="stat-icon">${icon('people',17)}</span><div class="order-detail"><h3>${esc(item.name || 'Sample visitor')}</h3><p class="order-meta">${esc(item.therapy_name)}</p>${status(textStatus(item.stage))}</div></div>`).join('') || empty('No partial leads','Saved sample sessions will appear here.','people')}</section></div></div>`;
  }
  function table(title, count, headers, rows, fallback) {
    return `<section class="card"><div class="table-caption"><h2>${esc(title)}</h2><span class="demo-tag">${count} ${count===1?'RECORD':'RECORDS'}</span></div>${count?`<div class="table-wrap" tabindex="0" aria-label="${esc(title)} table. Scroll horizontally on a small screen."><table class="data-table"><thead><tr>${headers.map(heading=>`<th scope="col">${esc(heading)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`:empty('Nothing to show',fallback)}</section>`;
  }
  function adminOrders(orders) {
    return table('Orders',orders.length,['Order / product','Therapy','Payment','Intake','Medical review','Total'],orders.map(order=>`<tr><td><strong>${esc(order.number)}</strong><div class="table-sub">${esc(order.product_name)}<br>${esc(order.plan_name)}</div></td><td>${esc(order.therapy_name)}</td><td>${status('Paid · demo','good')}</td><td>${intakeStatus(order)}</td><td>${status(textStatus(order.medical_status),order.medical_status==='awaiting_review'?'blue':'neutral')}</td><td><strong>${money(order)}</strong></td></tr>`).join(''),'No sample orders match this therapy.');
  }
  function adminIntakes(intakes) {
    return table('Intake queue',intakes.length,['Patient / order','Therapy','Status','Progress','Last saved'],intakes.map(item=>`<tr><td><strong>${esc(item.patient_name || 'Sample patient')}</strong><div class="table-sub">${esc(item.order_id)}</div></td><td>${esc(item.therapy_name)}</td><td>${status(textStatus(item.status),item.status==='submitted'?'good':'pending')}</td><td>${esc(item.answered || 0)} of ${esc(item.total || 0)} answers<div class="inline-progress"><span style="width:${item.total?Math.min(100,Math.round((item.answered||0)/item.total*100)):0}%"></span></div></td><td>${date(item.updated_at)}</td></tr>`).join(''),'No sample intake sessions match this therapy.');
  }
  function adminLeads(leads) {
    return notice('This view shows funnel progress, not medical answers. These are fictional leads in your isolated demo workspace.') + table('Partial leads',leads.length,['Sample lead','Therapy','Last step','Progress','Last activity'],leads.map(item=>`<tr><td><strong>${esc(item.name || 'Sample visitor')}</strong><div class="table-sub">${esc(item.email)}</div></td><td>${esc(item.therapy_name)}</td><td>${status(textStatus(item.stage))}</td><td>${esc(item.progress ?? 0)}%<div class="inline-progress"><span style="width:${Math.min(100,Math.max(0,Number(item.progress)||0))}%"></span></div></td><td>${date(item.updated_at)}</td></tr>`).join(''),'No sample leads match this therapy.');
  }
  async function loadSite() {
    const current = ++generation, site = state.site, role = state.role;
    state.loading = true; state.error = ''; state.intake = null; state.orderId = null; state.messages=[];
    state.dirtyVersion=0; state.savedVersion=0; state.saveError=''; state.fieldsError={}; state.messageDraft=''; state.messageId=null; state.sending=false;
    render();
    try {
      const [config, me, orders] = await Promise.all([request(endpoint('/configuration',site),{},role,site),request(endpoint('/me',site),{},'patient',site),request(endpoint('/orders',site),{},'patient',site)]);
      if (current!==generation) return;
      const overview = role==='admin' ? await request(endpoint('/admin/overview',site)+therapyQuery(),{},role,site) : null;
      if (current!==generation) return;
      state.config=config; state.patient=me.patient; state.orders=orders.orders || []; state.overview=overview;
    } catch (error) { if(current===generation) state.error=error.message; }
    finally { if(current===generation){ state.loading=false; render(); } }
  }
  async function loadView(view) {
    if (!await flushIntake()) return false;
    const current=++generation, site=state.site, role=state.role;
    state.view=view; state.error=''; state.fieldsError={}; state.loading=false;
    if (role==='admin') {
      state.loading=true; render();
      try { const overview=await request(endpoint('/admin/overview',site)+therapyQuery(),{},role,site); if(current!==generation)return false; state.overview=overview; }
      catch(error){ if(current!==generation)return false; state.error=error.message; }
      state.loading=false; render();
    } else if(view==='messages') {
      state.loading=true; render();
      try { const messages=await request(endpoint('/messages',site),{},role,site); if(current!==generation)return false; state.messages=messages.messages || []; }
      catch(error){ if(current!==generation)return false; state.error=error.message; }
      state.loading=false; render();
      document.getElementById('message-list')?.scrollTo(0,99999);
    } else if(view==='intake' && !state.intake && state.orders.length) {
      await openIntake(pendingOrders()[0]?.id || state.orders[0].id);
    } else render();
    return true;
  }
  async function openIntake(orderId) {
    if (!await flushIntake()) return;
    const current=++generation, site=state.site;
    state.loading=true; state.view='intake'; state.error=''; render();
    try {
      const intake=await request(endpoint(`/intakes/${encodeURIComponent(orderId)}`,site),{},'patient',site);
      if(current!==generation)return;
      state.intake=intake; state.intake.answers=state.intake.answers || {}; state.orderId=orderId;
      state.dirtyVersion=0; state.savedVersion=0; state.saveError=''; state.fieldsError={};
    } catch(error){ if(current!==generation)return; state.intake=null; state.error=error.message; }
    state.loading=false; render();
  }
  function updateSavedUI() {
    const element=document.getElementById('save-status');
    if(element){element.innerHTML=savedMarkup();element.classList.toggle('error',Boolean(state.saveError));}
    const errorElement=document.getElementById('intake-error');
    if(errorElement) errorElement.innerHTML=notice(state.saveError,'error');
    const completion=progress();
    const count=document.getElementById('progress-count'); if(count) count.textContent=`${completion.count} of ${completion.total} answered`;
    const percent=document.getElementById('progress-percent'); if(percent) percent.textContent=`${completion.percent}%`;
    const fill=document.getElementById('progress-fill'); if(fill) fill.style.width=`${completion.percent}%`;
  }
  function markDirty() {
    state.dirtyVersion++; state.saveError=''; clearTimeout(autosaveTimer);
    updateSavedUI(); autosaveTimer=setTimeout(()=>flushIntake(),600);
  }
  async function flushIntake() {
    clearTimeout(autosaveTimer);
    if(savePromise) { await savePromise; if(state.saveError) return false; }
    if(!state.intake || state.intake.status==='submitted' || state.dirtyVersion<=state.savedVersion) return true;
    const intake=state.intake, site=state.site, version=state.dirtyVersion;
    const answers=JSON.parse(JSON.stringify(intake.answers));
    const currentStep=intake.current_step || 0;
    state.saving=true; state.saveError=''; updateSavedUI();
    savePromise=(async()=>{
      try {
        const saved=await request(endpoint(`/intakes/${encodeURIComponent(state.orderId)}`,site),{method:'PATCH',body:JSON.stringify({revision:intake.revision,answers,current_step:currentStep})},'patient',site);
        if(state.intake===intake) {
          // A response may arrive after another keystroke. Preserve the current local answers.
          intake.revision=saved.revision; intake.updated_at=saved.updated_at; state.savedVersion=version;
        }
      } catch(error) {
        state.saveError=error.status===409?'This intake changed in another window. Your unsaved answers are still here; reload only after copying anything you need to keep.':error.message;
      } finally {state.saving=false;savePromise=null;updateSavedUI();}
    })();
    await savePromise;
    if(state.saveError) return false;
    if(state.dirtyVersion>state.savedVersion) return flushIntake();
    return true;
  }
  function validate(questions) {
    state.fieldsError={};
    questions.forEach(question=>{if(question.required&&!answered(question))state.fieldsError[question.id]='Please choose or enter a sample answer.';});
    if(Object.keys(state.fieldsError).length){
      const missing=questions.find(question=>state.fieldsError[question.id]);
      const sectionIndex=state.intake.template.sections.findIndex(section=>section.id===missing.section_id);
      if(sectionIndex>=0&&sectionIndex!==state.intake.current_step){state.intake.current_step=sectionIndex;markDirty();}
      render();document.querySelector('.field-error')?.closest('.field')?.querySelector('input,textarea')?.focus();return false;
    }
    return true;
  }
  async function changeStep(step) {
    const previous=Number(state.intake.current_step)||0;
    if(step>previous){
      const section=state.intake.template.sections[previous];
      if(!validate(visibleQuestions().filter(question=>question.section_id===section.id)))return;
    }
    state.intake.current_step=Math.max(0,Math.min(step,state.intake.template.sections.length-1));markDirty();
    if(await flushIntake()){render();document.querySelector('.intake-card')?.scrollIntoView({block:'start',behavior:'auto'});}
    else {state.intake.current_step=previous;state.dirtyVersion++;render();}
  }
  async function submitIntake() {
    if(!validate(visibleQuestions()))return;
    if(!await flushIntake())return;
    const current=++generation, site=state.site, orderId=state.orderId, revision=state.intake.revision;
    state.loading=true;render();
    try {
      const intake=await request(endpoint(`/intakes/${encodeURIComponent(orderId)}/submit`,site),{method:'POST',body:JSON.stringify({revision})},'patient',site);
      if(current!==generation)return;
      state.intake=intake;
      const orders=await request(endpoint('/orders',site),{},'patient',site);
      if(current!==generation)return;
      state.orders=orders.orders || [];
      announce('Sample intake submitted. No clinical approval has taken place.');
    }catch(error){if(current!==generation)return;state.error=error.message;}
    state.loading=false;render();
  }
  async function sendMessage() {
    const body=state.messageDraft.trim();
    if(!body || state.sending)return;
    const current=generation, site=state.site;
    state.sending=true;state.error='';
    if(!state.messageId)state.messageId=globalThis.crypto?.randomUUID?.() || `sample-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const messageId=state.messageId;
    render();
    try {
      const result=await request(endpoint('/messages',site),{method:'POST',body:JSON.stringify({body,client_message_id:messageId})},'patient',site);
      if(current!==generation){
        if(site===state.site&&state.role==='patient'&&state.messageId===messageId){
          state.sending=false;state.messageDraft='';state.messageId=null;
          if(state.view==='messages')await loadView('messages');
        }
        return;
      }
      state.messages=result.messages || [];state.messageDraft='';state.messageId=null;announce('Sample message sent.');
    }catch(error){
      if(current!==generation){
        if(site===state.site&&state.role==='patient'&&state.messageId===messageId){state.sending=false;if(state.view==='messages'){state.error=error.message;render();}}
        return;
      }
      state.error=error.message;
    }
    state.sending=false;render();document.getElementById('message-list')?.scrollTo(0,99999);
  }
  root.addEventListener('click',async event=>{
    const target=event.target.closest('[data-action]');if(!target)return;
    event.preventDefault();
    const action=target.dataset.action;
    if(action==='navigate')await loadView(target.dataset.view);
    if(action==='open-intake')await openIntake(target.dataset.order);
    if(action==='persona'&&target.dataset.role!==state.role){if(!await flushIntake())return;state.role=target.dataset.role;state.view='dashboard';state.therapy='';state.intake=null;await loadSite();}
    if(action==='intake-back')await changeStep(Number(state.intake.current_step||0)-1);
    if(action==='intake-next')await changeStep(Number(state.intake.current_step||0)+1);
    if(action==='intake-section')await changeStep(Number(target.dataset.step));
    if(action==='retry-save')await flushIntake();
    if(action==='submit-intake')await submitIntake();
    if(action==='sample-answers'){
      state.intake.template.questions.forEach(question=>{if(question.sample!==undefined)state.intake.answers[question.id]=Array.isArray(question.sample)?[...question.sample]:question.sample;});
      state.fieldsError={};markDirty();render();const saved=await flushIntake();announce(saved?'Fictional sample answers filled and saved.':'Fictional sample answers filled. Saving failed; use Retry to save.');
    }
    if(action==='restart'){sessionStorage.removeItem(STORAGE_KEY);await initialize();}
  });
  root.addEventListener('input',event=>{
    const target=event.target;
    if(target.id==='message-body'){if(!state.sending&&state.messageDraft!==target.value)state.messageId=null;state.messageDraft=target.value;return;}
    if(!target.dataset.question || target.type==='radio' || target.type==='checkbox')return;
    const question=state.intake.template.questions.find(item=>item.id===target.dataset.question);
    state.intake.answers[target.dataset.question]=question?.type==='number'?(target.value!==''?Number(target.value):null):target.value;
    delete state.fieldsError[target.dataset.question];markDirty();
  });
  root.addEventListener('change',async event=>{
    const target=event.target;
    if(target.id==='site-select'){
      const previous=state.site.id;
      if(!await flushIntake()){target.value=previous;return;}
      state.site=state.workspace.sites.find(site=>site.id===target.value);state.config=null;state.therapy='';state.view='dashboard';state.orders=[];state.overview=null;
      history.replaceState(null,'',`/${state.role==='admin'?'admin-demo':'portal'}/${encodeURIComponent(state.site.id)}`);await loadSite();return;
    }
    if(target.id==='therapy-filter'){state.therapy=target.value;await loadView(state.view);return;}
    if(target.dataset.question&&(target.type==='radio'||target.type==='checkbox')){
      const id=target.dataset.question;
      if(target.type==='checkbox'){
        const values=Array.isArray(state.intake.answers[id])?[...state.intake.answers[id]]:[];
        state.intake.answers[id]=target.checked?[...new Set([...values,target.value])]:values.filter(value=>value!==target.value);
      }else state.intake.answers[id]=target.value;
      delete state.fieldsError[id];markDirty();render();document.getElementById(target.id)?.focus();
    }
  });
  root.addEventListener('submit',event=>{event.preventDefault();if(event.target.id==='message-form')sendMessage();});
  window.addEventListener('beforeunload',event=>{if(state.dirtyVersion>state.savedVersion){event.preventDefault();event.returnValue='';}});
  async function initialize() {
    try {
      let saved;try{saved=JSON.parse(sessionStorage.getItem(STORAGE_KEY));}catch(_error){saved=null;}
      if(saved?.sites?.length&&(!saved.expires_at||new Date(saved.expires_at).getTime()>Date.now()))state.workspace=saved;
      else{state.workspace=await request('/api/demo/workspaces',{method:'POST',body:'{}'},'patient',null);sessionStorage.setItem(STORAGE_KEY,JSON.stringify(state.workspace));}
      const requested=decodeURIComponent(location.pathname.split('/')[2] || '');
      state.site=state.workspace.sites.find(site=>site.id===requested)||state.workspace.sites[0];
      if(!state.site)throw new Error('The sample workspace did not return any sites.');
      await loadSite();
    }catch(error){root.innerHTML=`<main class="boot"><h1>The demo could not load</h1><p>${esc(error.message)}</p>${button('Try a fresh demo workspace','restart','btn-primary')}</main>`;}
  }
  initialize();
})();
