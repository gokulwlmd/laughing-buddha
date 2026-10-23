"""Per-purchase care checkpoints. Care clocks never advance Sticky or billing.

Plans and question snapshots are scoped to a verified paid term and patient;
changing a master policy cannot rewrite an answer that was already submitted.
"""
from datetime import datetime, timedelta, timezone
import json
import secrets

from fastapi import HTTPException, Request, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from patient_demo.app import clean_answers, visible, IntakePatch, IntakeSubmit, IntakeResponse
from .provider import ProviderError


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z') if value is not None else None


class CareForm(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VerifySchedule(CareForm):
    shipment_interval_days: StrictInt = Field(ge=1, le=730)
    shipment_count: StrictInt = Field(ge=1, le=36)
    term_days: StrictInt = Field(ge=1, le=730)


class CareClock(CareForm):
    day_offset: StrictInt | None = Field(default=None, ge=0, le=730)


class TaskRefill(BaseModel):
    eligible: bool
    reason: str
    early_allowed: bool = False
    early_reason: str = ''
    request_id: str | None = None
    status: str | None = None


class TaskClaim(BaseModel):
    available: bool = False
    opens_at: str | None = None
    status: str = 'unavailable'
    claim_id: str | None = None
    order_id: str | None = None
    created_at: str | None = None
    reason: str = ''
    amount: str = '0.00'
    simulated: bool = False


class CareTask(BaseModel):
    claim: TaskClaim | None = None
    legacy_intake_status: str | None = None
    id: str
    label: str
    kind: str
    day_offset: int
    due_date: str
    opens_at: str
    request_opens_at: str
    status: str
    intake_status: str
    can_open: bool
    can_submit: bool
    required: bool
    refill_checkpoint: bool
    completed_at: str | None = None
    refill: TaskRefill


class Simulation(BaseModel):
    available: bool
    enabled: bool
    day_offset: int | None = None
    effective_date: str


class CarePlan(BaseModel):
    id: str | None = None
    term_order_id: str | None = None
    included_claims_enabled: bool = False
    initial_intake_required: bool = True
    initial_intake_complete: bool = False
    order_id: str
    sku: str
    schedule_verified: bool
    template_id: str
    coverage_days: int | None = None
    rule_revision: int = 0
    provider_connected: bool = False
    reason: str = ''
    simulation: Simulation
    tasks: list[CareTask]


class CareIntake(IntakeResponse):
    claim_id: str | None = None
    claim_order_id: str | None = None
    task_id: str
    provider_connected: bool = False
    simulated: bool = False


class IntakeHistory(BaseModel):
    intakes: list[CareIntake]


class CareManager:
    def __init__(self, service):
        self.s = service
        with service.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS member_care_plans(
                    id TEXT PRIMARY KEY,site_id TEXT NOT NULL,root_order_id TEXT NOT NULL,
                    term_order_id TEXT NOT NULL,patient_id TEXT NOT NULL,product_id TEXT NOT NULL,
                    sku TEXT NOT NULL,snapshot TEXT NOT NULL,created REAL NOT NULL,
                    UNIQUE(site_id,root_order_id,term_order_id,patient_id,product_id));
                CREATE TABLE IF NOT EXISTS member_care_intakes(
                    id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,task_id TEXT NOT NULL,
                    status TEXT NOT NULL,revision INTEGER NOT NULL,answers TEXT NOT NULL,
                    current_step INTEGER NOT NULL,template TEXT NOT NULL,updated REAL NOT NULL,
                    submitted REAL,submitted_answers TEXT,UNIQUE(plan_id,task_id));
                CREATE TABLE IF NOT EXISTS member_claim_intakes(
                    id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,task_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,claim_order_id TEXT NOT NULL,
                    status TEXT NOT NULL,revision INTEGER NOT NULL,answers TEXT NOT NULL,
                    current_step INTEGER NOT NULL,template TEXT NOT NULL,updated REAL NOT NULL,
                    submitted REAL,submitted_answers TEXT,simulated INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(plan_id,task_id,claim_id),UNIQUE(plan_id,task_id,claim_order_id));
                CREATE TABLE IF NOT EXISTS member_care_clocks(
                    site_id TEXT NOT NULL,order_id TEXT NOT NULL,day_offset INTEGER NOT NULL,
                    updated REAL NOT NULL,expires REAL NOT NULL,PRIMARY KEY(site_id,order_id));
                CREATE TABLE IF NOT EXISTS member_refill_tasks(
                    refill_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,task_id TEXT NOT NULL,
                    simulated INTEGER NOT NULL DEFAULT 0);
            ''')
            if 'simulated' not in {r[1] for r in db.execute('PRAGMA table_info(member_care_intakes)')}:
                db.execute('ALTER TABLE member_care_intakes ADD COLUMN simulated INTEGER NOT NULL DEFAULT 0')

    def configured(self, row):
        # Existing plans keep their mapping if the master policy is later edited.
        return bool(self.saved_plan(row) or self.s.rule(row['sku'], row['site_id']).get('intake_template_id'))

    def grant(self, row):
        with self.s.db() as db:
            grant = db.execute('SELECT patient_id FROM member_grants WHERE site_id=? AND order_id=?', (row['site_id'], row['order_id'])).fetchone()
        return grant['patient_id'] if grant else ''

    def saved_plan(self, row):
        snap = json.loads(row['snapshot'])
        with self.s.db() as db:
            record = db.execute('SELECT * FROM member_care_plans WHERE site_id=? AND root_order_id=? AND term_order_id=? AND patient_id=? AND product_id=?',
                (row['site_id'], snap.get('root_order_id', row['order_id']), snap.get('term_order_id', row['order_id']), self.grant(row), str(snap['product_id']))).fetchone()
        return dict(record) if record else None

    def settings(self, row):
        saved = self.saved_plan(row)
        return json.loads(saved['snapshot'])['rule'] if saved else self.s.rule(row['sku'], row['site_id'])

    def ensure(self, row):
        previous = self.saved_plan(row)
        if previous:
            return previous
        snap, raw, rule = json.loads(row['snapshot']), json.loads(row['payload']), self.s.rule(row['sku'], row['site_id'])
        if not rule.get('intake_template_id'):
            return None
        if not snap.get('schedule_verified'):
            return None
        setup = snap.get('product_setup') or {}
        count, interval = setup.get('shipment_count'), setup.get('shipment_interval_days')
        if count == 1 and not interval and snap.get('source') == 'checkout' and setup.get('term_months') in (1, 3):
            interval = setup['term_months'] * 30
        if not count or not interval:
            # A one-shipment term can be established by the purchased fixed-day
            # model, but never by parsing the SKU or today's master name.
            interval = raw['products'][0].get('billing_interval_days')
            count = 1 if interval and not raw['products'][0].get('prepaid') else None
        if type(count) is not int or type(interval) is not int or not 0 < count * interval <= 730:
            return None
        start = self.s.date(snap.get('term_started_at'))
        if start is None:
            return None
        days = rule.get('check_in_days') or []
        if (any(type(day) is not int or day <= 0 or day >= count * interval for day in days)
                or days != sorted(set(days))):
            raise HTTPException(409, 'This SKU’s care checkpoints need configuration within the verified paid term')
        patient_id = self.grant(row)
        if not patient_id:
            return None
        from .intake_templates import get_template
        try:
            templates = {'initial': get_template(rule['intake_template_id'], sku=row['sku'], kind='initial')}
            for day in days:
                templates['checkin-' + str(day)] = get_template(rule['intake_template_id'], sku=row['sku'], kind='checkin')
        except ValueError:
            raise HTTPException(409, 'The intake template does not match this product') from None
        data = {'rule': rule, 'start_date': start.isoformat(), 'coverage_days': count * interval,
                'product_setup': setup, 'templates': templates}
        plan_id = 'care_' + secrets.token_urlsafe(18)
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO member_care_plans VALUES(?,?,?,?,?,?,?,?,?)', (plan_id, row['site_id'],
                snap.get('root_order_id', row['order_id']), snap.get('term_order_id', row['order_id']), patient_id,
                str(snap['product_id']), row['sku'], encoded(data), self.s.clock()))
            actual = db.execute('SELECT id FROM member_care_plans WHERE site_id=? AND root_order_id=? AND term_order_id=? AND patient_id=? AND product_id=?',
                (row['site_id'], snap.get('root_order_id', row['order_id']), snap.get('term_order_id', row['order_id']), patient_id, str(snap['product_id']))).fetchone()
            # Adopt only the original term's matching initial intake. It never
            # becomes a later check-in or a subsequent renewal's questionnaire.
            legacy = db.execute('SELECT * FROM member_intakes WHERE site_id=? AND order_id=? AND patient_id=?',
                (row['site_id'], snap.get('term_order_id', row['order_id']), patient_id)).fetchone()
            if legacy and row['therapy_id'] == rule['intake_template_id']:
                db.execute('INSERT OR IGNORE INTO member_care_intakes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (legacy['id'], actual['id'], 'initial', legacy['status'], legacy['revision'], legacy['answers'], legacy['current_step'],
                     legacy['template'], legacy['updated'], legacy['submitted'], legacy['submitted_answers'], 0))
        return self.saved_plan(row)

    def simulation(self, row, plan=None):
        raw, snap = json.loads(row['payload']), json.loads(row['snapshot'])
        available = bool(snap.get('schedule_verified') and raw.get('test_order') is True
            and str(raw.get('gateway_id')) == '1' and raw['products'][0].get('is_shippable') is False)
        today = datetime.fromtimestamp(self.s.clock(), timezone.utc).date()
        with self.s.db() as db:
            record = db.execute('SELECT * FROM member_care_clocks WHERE site_id=? AND order_id=? AND expires>?', (row['site_id'], str(snap.get('term_order_id', row['order_id'])), self.s.clock())).fetchone()
        day = None
        if available and record:
            start = self.s.date(snap.get('term_started_at'))
            if start:
                day = record['day_offset']
                today = start + timedelta(days=day)
        return {'available': available, 'enabled': day is not None, 'day_offset': day, 'effective_date': today.isoformat()}

    def clock(self, row):
        sim = self.simulation(row)
        if not sim['enabled']:
            return self.s.clock()
        return datetime.fromisoformat(sim['effective_date']).replace(tzinfo=timezone.utc).timestamp() + 43200

    def raw_tasks(self, row, plan):
        data = json.loads(plan['snapshot'])
        rule, start = data['rule'], self.s.date(data['start_date'])
        today = self.s.date(self.simulation(row, plan)['effective_date'])
        expired = today >= start + timedelta(days=data['coverage_days'])
        with self.s.db() as db:
            intakes = {r['task_id']: dict(r) for r in db.execute('SELECT * FROM member_care_intakes WHERE plan_id=?', (plan['id'],))}
        tasks = []
        for day in [0] + rule.get('check_in_days', []):
            task_id = 'initial' if day == 0 else 'checkin-' + str(day)
            saved = intakes.get(task_id)
            required = (True if self.native_claims_enabled(row) else rule.get('initial_intake_required', True)) if day == 0 else rule.get('check_in_required', True)
            due = start + timedelta(days=day)
            opens = start if day == 0 else max(start + timedelta(days=int(rule.get('minimum_days', 0))), due - timedelta(days=int(rule.get('request_window_days', 14))))
            unlocked = today >= opens and (day == 0 or not expired)
            status = 'submitted' if saved and saved['status'] == 'submitted' else 'draft' if saved else 'available' if unlocked else 'locked'
            tasks.append({'id': task_id, 'label': 'Initial health intake' if day == 0 else f'Day {day} check-in',
                'kind': 'initial' if day == 0 else 'check_in', 'day_offset': day, 'due_date': due.isoformat(), 'opens_at': opens.isoformat(),
                'status': status, 'intake_status': saved['status'] if saved else 'not_started',
                'request_opens_at': opens.isoformat(), 'can_open': unlocked or bool(saved), 'can_submit': unlocked and status != 'submitted',
                'required': bool(required), 'refill_checkpoint': day != 0,
                'completed_at': stamp(saved['submitted']) if saved else None})
        # Only the currently applicable checkpoint may open for an early
        # request; enabling early requests never unlocks all future forms.
        checkpoints = [t for t in tasks if t['refill_checkpoint']]
        active = [t for t in checkpoints if self.s.date(t['request_opens_at']) <= today]
        early_task = (active[-1] if active else checkpoints[0]) if checkpoints else None
        live_rule = self.s.rule(row['sku'], row['site_id'])
        if early_task and rule.get('allow_early_requests') and live_rule.get('allow_early_requests') and not expired:
            early_start = start + timedelta(days=int(rule.get('early_request_minimum_days', 0)))
            if today >= early_start:
                early_task['opens_at'] = min(early_start, self.s.date(early_task['opens_at'])).isoformat()
                early_task['can_open'] = True
                early_task['can_submit'] = early_task['intake_status'] != 'submitted'
                if early_task['status'] == 'locked':
                    early_task['status'] = 'available'
        return tasks

    def native_claims_enabled(self, row):
        return bool(self.s.rule(row['sku'], row['site_id']).get('included_refills_enabled'))

    def claim_context(self, row, task_id):
        """Local scope and original-term evidence only; no provider side effect.

        ClaimsManager may call this without recursion: raw_tasks never calls
        ClaimsManager, and prior check-in states come from immutable care rows.
        """
        plan = self.ensure(row)
        if not plan:
            raise HTTPException(409, 'The original paid care schedule needs verification')
        snapshot = json.loads(row['snapshot'])
        data = json.loads(plan['snapshot'])
        tasks = self.raw_tasks(row, plan)
        task = next((task for task in tasks if task['id'] == task_id), None)
        if not task or task['kind'] != 'check_in':
            raise HTTPException(404, 'Included shipment checkpoint not found')
        setup = data.get('product_setup') or snapshot.get('product_setup') or {}
        interval, count = setup.get('shipment_interval_days'), setup.get('shipment_count')
        if (type(interval) is not int or type(count) is not int or interval <= 0 or count <= 1
                or task['day_offset'] % interval != 0 or not 0 < task['day_offset'] < interval * count):
            raise HTTPException(409, 'This checkpoint does not match an included shipment in the purchased term')
        start = self.s.date(data['start_date'])
        due = start + timedelta(days=task['day_offset'])
        window = int(self.s.rule(row['sku'], row['site_id']).get('claim_window_days', 20))
        with self.s.db() as db:
            initial = db.execute("SELECT status,simulated FROM member_care_intakes WHERE plan_id=? AND task_id='initial'", (plan['id'],)).fetchone()
            checks = db.execute('SELECT task_id,status,simulated,claim_id,claim_order_id FROM member_claim_intakes WHERE plan_id=?', (plan['id'],)).fetchall()
        earlier = []
        for preceding in tasks:
            if preceding['kind'] != 'check_in' or not preceding['required'] or preceding['day_offset'] >= task['day_offset']:
                continue
            complete = next((record for record in checks if record['task_id'] == preceding['id'] and record['status'] == 'submitted'), None)
            earlier.append({'task_id': preceding['id'], 'complete': bool(complete), 'simulated': bool(complete and complete['simulated'])})
        return {'plan': plan, 'task': task, 'snapshot': snapshot, 'target_cycle': task['day_offset'] // interval + 1,
            'start_date': start.isoformat(), 'due_date': due.isoformat(), 'opens_at': max(start + timedelta(days=int(self.s.rule(row['sku'], row['site_id']).get('minimum_days', 0))), due - timedelta(days=window)).isoformat(),
            'initial_complete': bool(initial and initial['status'] == 'submitted'), 'initial_simulated': bool(initial and initial['simulated']),
            'earlier_claim_checkins': earlier, 'included_claims_enabled': self.native_claims_enabled(row),
            'effective_date': self.simulation(row)['effective_date']}

    def tasks(self, row, plan):
        tasks = self.raw_tasks(row, plan)
        if not self.native_claims_enabled(row):
            return tasks
        manager = getattr(self.s, 'claims', None)
        for task in tasks:
            if task['kind'] != 'check_in':
                task['claim'] = {'available': False, 'status': 'not_applicable', 'reason': 'The initial shipment belongs to your original purchase.', 'amount': '0.00'}
                continue
            task['legacy_intake_status'] = task['intake_status']
            state = manager.task_state(row, plan, task) if manager else {'available': False, 'status': 'unavailable', 'reason': 'Included shipment claims are not connected yet.'}
            task['claim'] = state
            task['opens_at'] = state.get('opens_at') or task['opens_at']
            task['request_opens_at'] = task['opens_at']
            record = None
            if state.get('status') == 'claimed' and state.get('claim_id') and state.get('order_id'):
                with self.s.db() as db:
                    record = db.execute('SELECT * FROM member_claim_intakes WHERE plan_id=? AND task_id=? AND claim_id=? AND claim_order_id=?',
                        (plan['id'], task['id'], state['claim_id'], str(state['order_id']))).fetchone()
            claimed = state.get('status') == 'claimed' and bool(state.get('claim_id') and state.get('order_id'))
            task.update(intake_status=record['status'] if record else 'not_started',
                status='submitted' if record and record['status'] == 'submitted' else 'draft' if record else 'available' if claimed else 'locked',
                can_open=bool(claimed), can_submit=bool(claimed and (not record or record['status'] != 'submitted')),
                completed_at=stamp(record['submitted']) if record else None)
        return tasks

    def current_task(self, row, plan, tasks=None):
        tasks = tasks or self.raw_tasks(row, plan)
        today = self.s.date(self.simulation(row, plan)['effective_date'])
        checkpoints = [t for t in tasks if t['refill_checkpoint']]
        available = [t for t in checkpoints if self.s.date(t['request_opens_at']) <= today]
        return (available[-1] if available else checkpoints[0]) if checkpoints else tasks[0]

    def last_early(self, db, row, patient_id):
        raw, snap = json.loads(row['payload']), json.loads(row['snapshot'])
        simulated = self.simulation(row)['enabled']
        query = '''SELECT MAX(r.created) FROM member_refills r
            LEFT JOIN member_refill_tasks t ON t.refill_id=r.id
            WHERE r.site_id=? AND r.patient_id=? AND r.sku=? AND r.kind='early'
            AND COALESCE(t.simulated,0)=? AND r.test_only=?'''
        params = [row['site_id'], patient_id, row['sku'], int(simulated), int(bool(raw.get('test_order') or snap.get('payment_test_only')))]
        if simulated:
            query += ' AND t.plan_id IN (SELECT id FROM member_care_plans WHERE site_id=? AND root_order_id=? AND term_order_id=?)'
            params.extend([row['site_id'], snap.get('root_order_id', row['order_id']), snap.get('term_order_id', row['order_id'])])
        return db.execute(query, params).fetchone()[0]

    def availability(self, row, task_id=None):
        plan = self.ensure(row)
        raw, snap = json.loads(row['payload']), json.loads(row['snapshot'])
        line = raw['products'][0]
        result = {'eligible': False, 'reason': 'The original paid care schedule needs verification.', 'next_date': None,
                  'test_only': bool(raw.get('test_order') or snap.get('payment_test_only')), 'early_allowed': False, 'early_reason': ''}
        if not plan:
            return result
        data, tasks = json.loads(plan['snapshot']), self.raw_tasks(row, plan)
        rule = data['rule']
        if not any(t['refill_checkpoint'] for t in tasks):
            return result | {'reason': 'This plan includes one delivery. Manage your subscription renewal or choose a new paid plan.', 'next_date': line.get('next_billing_date')}
        applicable = self.current_task(row, plan, tasks)
        task = next((t for t in tasks if t['id'] == (task_id or applicable['id'])), None)
        if not task:
            raise HTTPException(404, 'Care checkpoint not found in this order')
        result.update(task_id=task['id'], next_date=task['due_date'], _plan_id=plan['id'],
            _cycle_key=f'care:{plan["id"]}:{task["id"]}', _simulated=self.simulation(row)['enabled'])
        current_rule = self.s.rule(row['sku'], row['site_id'])
        if self.native_claims_enabled(row):
            return result | {'reason': 'Use the included shipment claim when it becomes available, or choose a new paid plan from the store.'}
        if not rule.get('enabled') or not current_rule.get('enabled'):
            return result | {'reason': 'Refill requests are not enabled for this SKU.'}
        if raw.get('payment_status') not in ('approved', 'paid', 'captured'):
            return result | {'reason': 'The current payment status must be confirmed before a refill request.'}
        if result['test_only'] and not (rule.get('test_requests_enabled') and current_rule.get('test_requests_enabled')):
            return result | {'reason': 'This payment-test product does not provide medication refills.'}
        if line.get('is_shippable') is not True and not (result['test_only'] and rule.get('test_requests_enabled')):
            return result | {'reason': 'This product does not have a verified medication delivery entitlement.'}
        if line.get('billing_status') == 'held' or line.get('on_hold') is True or (line.get('is_recurring') and line.get('billing_status') != 'active'):
            return result | {'reason': 'Refill access requires an active billing entitlement.'}
        with self.s.db() as db:
            related = db.execute('SELECT * FROM member_orders WHERE site_id=? AND customer_id=? AND sku=?', (row['site_id'], row['customer_id'], row['sku'])).fetchall()
        for other in related:
            other_snap, other_raw = json.loads(other['snapshot']), json.loads(other['payload'])
            if (int(other['order_id']) > int(row['order_id']) and other_snap.get('root_order_id') == snap.get('root_order_id')
                    and other_raw['products'][0].get('subscription_id') == line.get('subscription_id')):
                return result | {'reason': 'Use the latest verified order in this subscription for a refill review.'}
        if task['id'] != applicable['id'] or not task['refill_checkpoint']:
            return result | {'reason': 'Use the current scheduled check-in for a refill request.'}
        today, start = self.s.date(self.simulation(row)['effective_date']), self.s.date(data['start_date'])
        if today >= start + timedelta(days=data['coverage_days']):
            return result | {'reason': 'This paid care term has ended. A new verified term is required.'}
        if not self.simulation(row)['available']:
            contributing_ids = [checkpoint['id'] for checkpoint in tasks
                if checkpoint['id'] == task['id'] or (checkpoint['required'] and checkpoint['day_offset'] <= task['day_offset'])]
            placeholders = ','.join('?' for _ in contributing_ids)
            with self.s.db() as db:
                simulated_answers = db.execute(
                    "SELECT 1 FROM member_care_intakes WHERE plan_id=? AND task_id IN (" + placeholders + ") AND status='submitted' AND simulated=1",
                    (plan['id'], *contributing_ids)).fetchone()
            if simulated_answers:
                return result | {'reason': 'Simulated check-ins cannot qualify a live medication refill. Contact the care team.'}
        outstanding = [t for t in tasks if t['day_offset'] < task['day_offset'] and t['required'] and t['intake_status'] != 'submitted']
        if outstanding:
            return result | {'reason': 'Complete your earlier required intake and check-ins before requesting this refill.'}
        if task['required'] and task['intake_status'] != 'submitted':
            return result | {'reason': 'Complete this scheduled check-in before requesting its refill.'}
        minimum = start + timedelta(days=int(rule.get('minimum_days', 0)))
        scheduled = today >= max(minimum, self.s.date(task['request_opens_at']))
        with self.s.db() as db:
            last = self.last_early(db, row, plan['patient_id'])
        early_minimum = start + timedelta(days=int(rule.get('early_request_minimum_days', 0)))
        early = bool(rule.get('allow_early_requests') and current_rule.get('allow_early_requests')) and today >= early_minimum and (last is None or self.clock(row) >= last + int(rule.get('early_request_cooldown_days', 7)) * 86400)
        result.update(early_allowed=early, early_reason='Request an early refill review.' if early else 'Early refill requests are not enabled or their waiting period has not ended.')
        if not scheduled:
            return result | {'reason': 'Your next refill request window has not opened yet.'}
        return result | {'eligible': True, 'reason': 'Request review for this check-in. No shipment or charge is created automatically.'}

    def public(self, row):
        if not self.configured(row):
            return None
        plan = self.ensure(row)
        rule = self.settings(row)
        response = {'order_id': row['order_id'], 'sku': row['sku'], 'schedule_verified': bool(json.loads(row['snapshot']).get('schedule_verified')),
            'template_id': rule.get('intake_template_id', ''), 'coverage_days': None, 'rule_revision': rule.get('revision', 0),
            'provider_connected': False, 'reason': '', 'simulation': self.simulation(row), 'tasks': []}
        if not plan:
            response['reason'] = 'Verify the original paid schedule and connect this order to a patient account to prepare its care plan.'
            return response
        response['id'] = plan['id']
        response['term_order_id'] = plan['term_order_id']
        response['coverage_days'] = json.loads(plan['snapshot'])['coverage_days']
        response['included_claims_enabled'] = self.native_claims_enabled(row)
        current_tasks = self.tasks(row, plan)
        response['initial_intake_required'] = current_tasks[0]['required']
        response['initial_intake_complete'] = current_tasks[0]['intake_status'] == 'submitted'
        for task in current_tasks:
            availability = self.availability(row, task['id'])
            with self.s.db() as db:
                request = db.execute('SELECT r.id,r.status FROM member_refills r JOIN member_refill_tasks t ON r.id=t.refill_id WHERE t.plan_id=? AND t.task_id=? ORDER BY r.created DESC LIMIT 1', (plan['id'], task['id'])).fetchone()
            task['refill'] = {key: availability.get(key, False if key in ('eligible', 'early_allowed') else '') for key in ('eligible', 'reason', 'early_allowed', 'early_reason')}
            task['refill'].update(request_id=request['id'] if request else None, status=request['status'] if request else None)
            response['tasks'].append(task)
        return response

    def intake(self, row, patient, task_id, create=True):
        plan = self.ensure(row)
        if not plan or plan['patient_id'] != patient['id']:
            raise HTTPException(409, 'The original paid care schedule needs verification before this intake can open')
        task = next((t for t in self.tasks(row, plan) if t['id'] == task_id), None)
        if not task:
            raise HTTPException(404, 'Care checkpoint not found in this order')
        if self.native_claims_enabled(row) and task['kind'] == 'check_in':
            claim = task.get('claim') or {}
            if claim.get('status') != 'claimed' or not claim.get('claim_id') or not claim.get('order_id'):
                raise HTTPException(409, 'Claim this included shipment before completing its check-in')
            with self.s.db() as db:
                intake = db.execute('SELECT * FROM member_claim_intakes WHERE plan_id=? AND task_id=? AND claim_id=? AND claim_order_id=?',
                    (plan['id'], task_id, claim['claim_id'], str(claim['order_id']))).fetchone()
                if not intake and create:
                    template = json.loads(plan['snapshot'])['templates'][task_id]
                    template, answers = self.s.answer_profile.seed(db, row, patient, template)
                    db.execute('INSERT OR IGNORE INTO member_claim_intakes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('intake_' + secrets.token_urlsafe(18), plan['id'], task_id, claim['claim_id'], str(claim['order_id']), 'draft', 0, encoded(answers), 0,
                         encoded(template), self.s.clock(), None, None, int(self.simulation(row)['enabled'] or bool(claim.get('simulated')))))
                    intake = db.execute('SELECT * FROM member_claim_intakes WHERE plan_id=? AND task_id=? AND claim_id=? AND claim_order_id=?',
                        (plan['id'], task_id, claim['claim_id'], str(claim['order_id']))).fetchone()
            if intake:
                with self.s.db() as db:
                    intake = self.s.answer_profile.hydrate(db, row, patient, intake, 'member_claim_intakes')
            return plan, task, dict(intake, _table='member_claim_intakes') if intake else None
        with self.s.db() as db:
            intake = db.execute('SELECT * FROM member_care_intakes WHERE plan_id=? AND task_id=?', (plan['id'], task_id)).fetchone()
        if not intake and not task['can_submit']:
            raise HTTPException(409, 'This check-in is outside its available care window')
        if not intake and create:
            template = json.loads(plan['snapshot'])['templates'][task_id]
            with self.s.db() as db:
                template, answers = self.s.answer_profile.seed(db, row, patient, template)
                db.execute('INSERT OR IGNORE INTO member_care_intakes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', ('intake_' + secrets.token_urlsafe(18), plan['id'], task_id, 'draft', 0, encoded(answers), 0, encoded(template), self.s.clock(), None, None, int(self.simulation(row)['enabled'])))
                intake = db.execute('SELECT * FROM member_care_intakes WHERE plan_id=? AND task_id=?', (plan['id'], task_id)).fetchone()
        if intake:
            with self.s.db() as db:
                intake = self.s.answer_profile.hydrate(db, row, patient, intake, 'member_care_intakes')
        return plan, task, dict(intake) if intake else None

    def intake_public(self, row, record):
        return {'claim_id': record.get('claim_id'), 'claim_order_id': record.get('claim_order_id'), 'id': record['id'], 'task_id': record['task_id'], 'order_id': row['order_id'], 'therapy_id': row['therapy_id'],
            'status': record['status'], 'revision': record['revision'], 'answers': json.loads(record['answers']),
            'current_step': record['current_step'], 'updated_at': stamp(record['updated']), 'submitted_at': stamp(record['submitted']),
            'template': json.loads(record['template']), 'reused_fields': [q['id'] for q in json.loads(record['template'])['questions'] if q.get('reuse_status') in ('stable', 'verified')], 'provider_connected': False, 'simulated': bool(record['simulated'])}

    def modify(self, row, patient, task_id, body, submit=False):
        plan, task, record = self.intake(row, patient, task_id)
        if not task['can_submit']:
            raise HTTPException(409, 'This check-in is submitted or outside its available care window')
        table = record.get('_table', 'member_care_intakes')
        assert table in ('member_care_intakes', 'member_claim_intakes')
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            record = dict(db.execute('SELECT * FROM ' + table + ' WHERE id=?', (record['id'],)).fetchone())
            if record['status'] == 'submitted' or record['revision'] != body.revision:
                raise HTTPException(409, 'This check-in is submitted or changed. Reload before saving.')
            answers, template, now = json.loads(record['answers']), json.loads(record['template']), self.s.clock()
            self.s.answer_profile.validate(db, row, patient, template, incoming=None if submit else body.answers, submit=submit, answers=answers)
            if submit:
                questions = [q for q in template['questions'] if visible(q, answers)]
                missing = [q['id'] for q in questions if q.get('required') and answers.get(q['id']) in (None, '', [])]
                if missing:
                    raise HTTPException(422, {'code': 'required_answers_missing', 'question_ids': missing})
                answers = {q['id']: answers[q['id']] for q in questions if q['id'] in answers}
                db.execute("UPDATE " + table + " SET status='submitted',revision=revision+1,answers=?,submitted_answers=?,updated=?,submitted=?,simulated=? WHERE id=?", (encoded(answers), encoded(answers), now, now, int(record['simulated'] or self.simulation(row)['enabled']), record['id']))
            else:
                for key, value in clean_answers(template, body.answers).items():
                    if value is None:
                        answers.pop(key, None)
                    else:
                        answers[key] = value
                step = record['current_step'] if body.current_step is None else body.current_step
                if not 0 <= step < len(template['sections']):
                    raise HTTPException(422, 'Unknown intake step')
                db.execute('UPDATE ' + table + ' SET answers=?,current_step=?,revision=revision+1,updated=? WHERE id=?', (encoded(answers), step, now, record['id']))
            record = dict(db.execute('SELECT * FROM ' + table + ' WHERE id=?', (record['id'],)).fetchone())
        return self.intake_public(row, record)

    def verify_schedule(self, site_id, order_id, body):
        row = self.s.sync(site_id, order_id)
        snap = json.loads(row['snapshot'])
        if body.term_days != body.shipment_count * body.shipment_interval_days:
            raise HTTPException(422, 'The complete term must match its shipment count and interval')
        if snap.get('term_order_id', order_id) != order_id:
            raise HTTPException(409, 'Verify the original order for this paid term')
        try:
            evidence = self.s.provider.verify_care_schedule(order_id, expected_campaign=self.s.site(site_id)[0]['campaign_id'], expected_customer_id=row['customer_id'], **body.model_dump())
        except ProviderError:
            raise HTTPException(409, 'The original product, prepaid offer and fixed-day billing model could not verify this care schedule') from None
        if (str(evidence.get('product_id')) != str(snap['product_id']) or str(evidence.get('term_order_id')) != order_id
                or self.s.date(evidence.get('term_started_at')) != self.s.date(snap.get('term_started_at'))):
            raise HTTPException(409, 'The verified evidence does not match this purchased term')
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            related = db.execute('SELECT * FROM member_orders WHERE site_id=? AND customer_id=?', (site_id, row['customer_id'])).fetchall()
            for related_row in related:
                candidate = json.loads(related_row['snapshot'])
                if (candidate.get('root_order_id') == snap.get('root_order_id') and candidate.get('term_order_id') == order_id
                        and str(candidate['product_id']) == str(snap['product_id'])):
                    candidate.update(schedule_verified=True, care_schedule_evidence=evidence,
                        product_setup=dict(candidate.get('product_setup') or {}, shipment_interval_days=body.shipment_interval_days, shipment_count=body.shipment_count))
                    db.execute('UPDATE member_orders SET snapshot=? WHERE site_id=? AND order_id=?', (encoded(candidate), site_id, related_row['order_id']))
        return {'verified': True, 'care_plan': self.public(self.s.order_record(site_id, order_id))}

    def set_clock(self, site_id, order_id, body):
        row = self.s.sync(site_id, order_id)
        term_order_id = str(json.loads(row['snapshot']).get('term_order_id', order_id))
        if body.day_offset is None:
            with self.s.db() as db:
                db.execute('DELETE FROM member_care_clocks WHERE site_id=? AND order_id=?', (site_id, term_order_id))
            return {'care_plan': self.public(row)}
        plan = self.ensure(row)
        if not self.simulation(row)['available'] or not plan:
            raise HTTPException(409, 'Care simulation requires a verified non-shippable Dry Run order and an enrolled patient')
        if body.day_offset > json.loads(plan['snapshot'])['coverage_days']:
            raise HTTPException(422, 'Choose a day within the verified term, including its end date')
        with self.s.db() as db:
            db.execute('INSERT INTO member_care_clocks VALUES(?,?,?,?,?) ON CONFLICT(site_id,order_id) DO UPDATE SET day_offset=excluded.day_offset,updated=excluded.updated,expires=excluded.expires',
                (site_id, term_order_id, body.day_offset, self.s.clock(), self.s.clock() + 86400))
        return {'care_plan': self.public(row)}


    def attach(self, router, owner, auth):
        @router.get('/orders/{order_id}/care-plan', response_model=CarePlan)
        def plan(site_id: str, order_id: str, patient=Depends(auth)):
            row = self.s.order_record(site_id, order_id, patient)
            result = self.public(row)
            if result is None:
                raise HTTPException(409, 'This product does not have an assigned intake template yet')
            return result

        @router.get('/orders/{order_id}/care-tasks/{task_id}/intake-history', response_model=IntakeHistory)
        def intake_history(site_id: str, order_id: str, task_id: str, patient=Depends(auth)):
            row = self.s.order_record(site_id, order_id, patient)
            plan = self.ensure(row)
            if not plan or plan['patient_id'] != patient['id']:
                raise HTTPException(404, 'Care plan not found in this account')
            if not any(t['id'] == task_id for t in self.raw_tasks(row, plan)):
                raise HTTPException(404, 'Care checkpoint not found in this order')
            with self.s.db() as db:
                old = db.execute('SELECT * FROM member_care_intakes WHERE plan_id=? AND task_id=?', (plan['id'], task_id)).fetchall()
                claimed = db.execute('SELECT * FROM member_claim_intakes WHERE plan_id=? AND task_id=?', (plan['id'], task_id)).fetchall()
            records = sorted([dict(record) for record in old] + [dict(record) for record in claimed], key=lambda record: record['updated'])
            return {'intakes': [self.intake_public(row, record) for record in records]}

        @router.get('/orders/{order_id}/care-tasks/{task_id}/intake', response_model=CareIntake)
        def get_intake(site_id: str, order_id: str, task_id: str, patient=Depends(auth)):
            row = self.s.order_record(site_id, order_id, patient)
            if task_id == 'initial':
                return self.s.initial_intake(row, patient) | {'task_id': 'initial'}
            _, _, record = self.intake(row, patient, task_id)
            return self.intake_public(row, record)

        @router.patch('/orders/{order_id}/care-tasks/{task_id}/intake', response_model=CareIntake)
        def patch_intake(site_id: str, order_id: str, task_id: str, body: IntakePatch, patient=Depends(auth)):
            row = self.s.order_record(site_id, order_id, patient)
            if task_id == 'initial':
                return self.s.modify_initial(row, body, patient) | {'task_id': 'initial'}
            return self.modify(row, patient, task_id, body)

        @router.post('/orders/{order_id}/care-tasks/{task_id}/intake/submit', response_model=CareIntake)
        def submit_intake(site_id: str, order_id: str, task_id: str, body: IntakeSubmit, patient=Depends(auth)):
            row = self.s.order_record(site_id, order_id, patient)
            if task_id == 'initial':
                return self.s.modify_initial(row, body, patient, True) | {'task_id': 'initial'}
            return self.modify(row, patient, task_id, body, True)

        @owner.post('/orders/{order_id}/verify-care-schedule')
        def verify(site_id: str, order_id: str, body: VerifySchedule, req: Request):
            self.s.admin.authenticated(req, True)
            return self.verify_schedule(site_id, order_id, body)

        @owner.post('/orders/{order_id}/care-clock')
        def set_clock(site_id: str, order_id: str, body: CareClock, req: Request):
            self.s.admin.authenticated(req, True)
            return self.set_clock(site_id, order_id, body)
