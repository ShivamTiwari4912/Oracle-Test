"""
Oracle Field Service - Online Skill Test v2 (Admin guide + Fundamentals based)
--------------------------------------------------------
Run:    pip install flask
        python app.py
Open:   http://localhost:5000        (student)
        http://localhost:5000/admin?key=ofs-admin   (trainer dashboard)

Change ADMIN_KEY / DURATION / MARKS below (or via environment variables).
Correct answers never leave the server; options are shuffled per attempt.
"""
import csv, io, json, os, random, secrets, sqlite3, time
from datetime import datetime
from flask import Flask, Response, abort, jsonify, redirect, request

# ----------------------------- CONFIG ---------------------------------------
DURATION_SEC = int(os.getenv("DURATION_MIN", "180")) * 60   # 3 hours
MARK_PER_Q = float(os.getenv("MARK_PER_Q", "1"))            # marks for a correct answer
NEGATIVE = float(os.getenv("NEGATIVE_MARK", "0"))           # marks cut for a wrong answer
PASS_PERCENT = int(os.getenv("PASS_PERCENT", "60"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "ofs-admin")
GRACE_SEC = 15
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ofs_test_v2.db")
TEST_TITLE = "Oracle Field Service - Skill Check"

app = Flask(__name__)

# ----------------------------- TOPICS ---------------------------------------
TOPICS = {
    "FUND": ("Field Service Fundamentals", [
        "Revise the 5 key features of field service (on-site, mobile, time-bound, skill-dependent, unpredictable) and the 6-step lifecycle (PPT slides 4-6).",
        "Revise what OFS does: cloud-based, end to end, connected, and its core capabilities (PPT slides 7-9)."]),
    "ROLE": ("Roles & Responsibilities", [
        "Make a table of the 4 roles (technician, dispatcher, customer, administrator) with who does what in one job (PPT slides 10-15).",
        "Practise deciding who acts when a plan changes: delay, missing part, nobody at home."]),
    "TERM": ("Core Terms & Statuses", [
        "Revise service request, work order, activity, resource and territory, and how one becomes the next (PPT slides 16-23).",
        "Learn the 6 activity statuses and when each is used, especially Suspended vs Not Done vs Cancelled (PPT slide 20)."]),
    "RES": ("Resources & Resource Tree", [
        "Revise the resource tree, resource types, inheritance and visibility rule: a person sees their own unit and everything below it (Guide, Section 3).",
        "Revise the steps to add a technician: info, skills with ratio, zones, calendar, then the user login."]),
    "SEC": ("Users & Security", [
        "Revise the difference between User Type (screens, actions, fields) and linked resource (visible part of the tree) (Guide, Section 4).",
        "Revise SSO, password rules, Applications for APIs, and how to handle leavers."]),
    "WORK": ("Work Definition", [
        "Revise work skills with ratio, work zones with one key field, time slots and activity types with features (Guide, Section 5).",
        "Practise the 'four things must match' idea: skill, zone, time and calendar."]),
    "CAP": ("Capacity & Quota", [
        "Revise capacity (calculated) vs quota (your decision) with the worked example 10 x 240 min and 80% quota (Guide, Section 6).",
        "Revise capacity areas and categories, and what happens when the category mapping is wrong."]),
    "ROUT": ("Routing & Scheduling", [
        "Revise routing plan (what and when), routing profile (how), bulk and immediate runs (Guide, Section 7).",
        "Revise the admin tuning checklist: statistics, up-to-date skills, zones and calendars, and reviewing unassigned jobs after every run."]),
    "CONF": ("Screens, Rules & Plugins", [
        "Revise the decision ladder: configure first, rules and messages second, plugin last (Guide, Section 8).",
        "Practise setting up a message scenario: trigger, condition, channel and placeholders."]),
    "INT": ("Integration & APIs", [
        "Revise which REST API is used for what: Core, Capacity, Quota, Metadata, Collaboration (Guide, Section 9).",
        "Revise Applications (one per system, client ID and secret), OAuth 2.0 tokens, and the status mapping with Fusion Service."]),
    "OPS": ("Operations & Troubleshooting", [
        "Learn the 'why is this job unassigned?' checklist and follow it top to bottom (Guide, Section 10).",
        "Revise the daily, weekly and quarterly admin routine and the Test-first rule (Guide, Section 11)."]),
}
LEVELS = {"basic": "Basic", "mid": "Intermediate", "scenario": "Scenario-based"}


def Q(topic, level, q, opts, why):
    # opts[0] is ALWAYS the correct answer; options are shuffled per attempt on the server.
    return dict(topic=topic, level=level, q=q, options=opts, why=why)


_RAW = [
    # ---------------- BASIC (10) ----------------
    Q("FUND", "basic", "A dispatcher keeps changing the daily plan because jobs overrun and urgent requests arrive. Which key feature of field service explains this?",
      ["It is unpredictable: jobs can overrun and urgent requests can arrive",
       "It is on-site: the work happens at the customer's location",
       "It is time-bound: customers expect a confirmed visit window",
       "It is skill-dependent: each job needs the right skills, tools and parts"],
      "Unpredictability is the reason plans change during the day (PPT slide 4). The other features describe where, when and with what the work is done."),
    Q("FUND", "basic", "Without a system, a technician reaches the customer but a needed part is missing from the van. What is the usual result?",
      ["A second visit is needed",
       "The job cannot be completed because the wrong technician was sent",
       "Managers cannot see the delay because there is no live status",
       "The customer is unhappy because the appointment was double-booked"],
      "In the 'Challenges without a system' table (PPT slide 6), missing parts or tools lead to a second visit. The other results belong to other challenges in the same table."),
    Q("ROLE", "basic", "Which task belongs to the Dispatcher and NOT to the Administrator?",
      ["Moving less urgent work so that an urgent job can be inserted into a route",
       "Creating users, resources and work zones",
       "Defining activity types and business rules",
       "Managing the integrations with other systems"],
      "Dispatchers keep the daily plan working and handle urgent jobs (PPT slide 12). Administrators set up and maintain the system (PPT slide 14)."),
    Q("TERM", "basic", "Which sentence describes a 'work order' correctly?",
      ["A formal job record that states the work, location and priority; one request can lead to several of them",
       "The customer's request for help, usually created by a call, portal or message",
       "A schedulable task with a date, time window and duration",
       "The service area that is covered by a team or a resource"],
      "The second option is a service request, the third is an activity and the fourth is a territory (PPT slides 17-22)."),
    Q("TERM", "basic", "A technician has paused the work and plans to continue it later. Which activity status should be used?",
      ["Suspended", "Not Done", "Pending", "Cancelled"],
      "Suspended = paused, to be continued. Not Done = the visit could not be performed. Pending = scheduled, not started. Cancelled = no longer required (PPT slide 20)."),
    Q("RES", "basic", "Which sentence about a 'bucket' in OFS is correct?",
      ["It is a resource that holds jobs for a group; jobs wait there before they are assigned",
       "It is a user type that decides which screens a person can open",
       "It is a booking window that is shown to the customer",
       "It is a skill that a technician has, with a ratio in percent"],
      "A bucket is a resource that holds jobs for a group, such as the Ghaziabad bucket (Guide, Section 1 key words)."),
    Q("WORK", "basic", "What is a 'time slot' in OFS?",
      ["A booking window shown to the customer, for example 12:00-16:00",
       "The total working minutes that OFS calculates for an area",
       "The part of capacity that the admin allows to be sold",
       "An area on the map that is found from the postal code"],
      "Time slots are booking windows (Guide, Section 5). The other options describe capacity, quota and a work zone."),
    Q("CAP", "basic", "Which statement separates capacity from quota correctly?",
      ["Capacity is calculated by OFS from calendars, skills and zones; quota is the part the admin allows to be sold",
       "Capacity is typed by the admin; quota is calculated by OFS from the calendars",
       "Both are typed by the admin for every time slot",
       "Both are calculated by OFS and the admin cannot change them"],
      "You cannot type capacity. Quota is your decision (Guide, Section 6)."),
    Q("CONF", "basic", "A business asks 'can OFS do X?'. According to the decision ladder, what should the admin try first?",
      ["Configure it with standard screens and settings, with no code",
       "Write a business rule or a message scenario",
       "Build a plugin with HTML and JavaScript",
       "Create a custom integration through the REST API"],
      "Configure first, rules and messages second, plugin or API last. Every plugin must be tested again after each quarterly update (Guide, Section 8)."),
    Q("OPS", "basic", "Which task belongs to the admin's daily 15-minute morning check?",
      ["Check that last night's routing run finished and see how many activities are unassigned and why",
       "Read the Oracle release notes and run a regression test",
       "Review quota against real use for every area",
       "Update the duration and travel statistics from real jobs"],
      "The second and fourth tasks are quarterly. The third is weekly (Guide, Section 11)."),

    # ---------------- INTERMEDIATE (15) ----------------
    Q("FUND", "mid", "Which pair describes the OFS features 'Cloud-based' and 'Connected' correctly?",
      ["Cloud-based: used through a browser and mobile app with no local installation. Connected: shares data with service, CRM and ERP systems",
       "Cloud-based: shares data with service, CRM and ERP systems. Connected: needs no local installation",
       "Cloud-based: covers planning, routing and completion. Connected: works only without internet",
       "Cloud-based: works only on the mobile app. Connected: the technician must stay online all day"],
      "PPT slide 7. The first option keeps each feature with its own meaning."),
    Q("ROLE", "mid", "Which statement about the Dispatcher in OFS is correct?",
      ["Dispatchers do not do the jobs; they use the Dispatch Console to review automatic schedules and fix exceptions",
       "Dispatchers perform the second visit when the technician cannot finish the work",
       "Dispatchers control access rights and decide how the system behaves for all users",
       "Dispatchers request the service and agree on the appointment window"],
      "PPT slide 12. Access rights belong to the administrator and the request belongs to the customer."),
    Q("TERM", "mid", "Priya says 'my internet is not working'. A support agent then records 'repair router and line fault at Priya's address' with the skills needed. Which two terms are these, in order?",
      ["Service request, then work order",
       "Work order, then activity",
       "Service request, then activity",
       "Activity, then resource"],
      "The complaint is the service request. The formal job record is the work order. OFS then creates the activity (PPT slides 23-26)."),
    Q("RES", "mid", "A Ghaziabad dispatcher cannot see anything under the Noida bucket. Which design idea of OFS causes this?",
      ["A person sees their own resource and everything below it in the resource tree",
       "A dispatcher sees only resources that have the same work skills",
       "A dispatcher sees only resources that use the same time slots",
       "A dispatcher sees only resources of the same activity type"],
      "The resource tree is also the first security layer (Guide, Section 3)."),
    Q("SEC", "mid", "Every OFS user has one User Type and one linked resource. What does each one decide?",
      ["User Type decides screens, actions and fields; the linked resource decides which part of the tree the user sees",
       "User Type decides which part of the tree the user sees; the linked resource decides screens and actions",
       "User Type decides the work zones; the linked resource decides the password rules",
       "User Type decides the time slots; the linked resource decides the routing plan"],
      "Guide, Section 4. A wrong user type changes what a person can do; a wrong resource changes what they can see."),
    Q("SEC", "mid", "A technician opens an activity, sees 'Warranty status' as read-only, and 'Internal cost' is hidden. Which permission layer controls this?",
      ["Fields (editable, read-only or hidden)",
       "Screens (which menus the user sees)",
       "Actions (create, move, delete, reopen)",
       "Resource visibility in the tree"],
      "The three layers are screens, actions and fields. Showing, locking or hiding a property is a field-level setting (Guide, Section 4)."),
    Q("WORK", "mid", "A technician has the skill 'AC-Install' with a ratio of 80%. What does this mean?",
      ["The technician can do the work but is a little slower",
       "The technician can do only 80% of the steps of an installation",
       "The technician works 80% of the day on this skill",
       "The skill is allowed only on 80% of the work zones"],
      "100% means fully skilled, a lower ratio means slower, and 0% means cannot do (Guide, Sections 3 and 5)."),
    Q("WORK", "mid", "Why does the guide advise using the same key field (for example postal code) for all work zones?",
      ["So that OFS always checks one field when it finds the zone of a job address",
       "So that technicians do not need a work calendar",
       "So that quota is calculated faster",
       "So that activity types do not need skills"],
      "If some zones use postal code and some use city, the zone may not be found (Guide, Section 5)."),
    Q("CAP", "mid", "A capacity category contains the skill AC-Repair, but the activity type EMERGENCY_REPAIR was not added to it. What is the likely result?",
      ["Booking slots for that kind of work do not show",
       "Quota for the category becomes 100% automatically",
       "Capacity for all categories becomes zero",
       "The nightly routing plan stops running"],
      "The skill and the activity type must both be mapped, or slots never show (Guide, Section 6, common mistakes)."),
    Q("ROUT", "mid", "What is the difference between a bulk run and an immediate run in routing?",
      ["Bulk runs the full set on a schedule, such as nightly for tomorrow; immediate routes each new activity as it arrives",
       "Bulk routes each new activity as it arrives; immediate runs the full set every night",
       "Bulk is used only for emergencies; immediate is used only for installations",
       "Bulk changes technician skills; immediate changes the quota"],
      "Guide, Section 7, Figure 9: nightly bulk run at 20:00, immediate run for an emergency at 11:20."),
    Q("ROUT", "mid", "Which pair describes a Routing Plan and a Routing Profile correctly?",
      ["Plan = WHAT and WHEN (scope, timing, action). Profile = HOW (goals such as less travel and respecting SLA)",
       "Plan = HOW (goals such as less travel). Profile = WHAT and WHEN (scope and timing)",
       "Plan = the list of skills. Profile = the list of work zones",
       "Plan = the quota values. Profile = the capacity values"],
      "Guide, Section 7. The plan decides what is routed and when; the profile decides how the goals are balanced."),
    Q("CONF", "mid", "The business rule is: 'If a job is marked Not Done, the reason is mandatory.' Which OFS tool matches this need best?",
      ["Business Rules (event-driven, low code)",
       "Message Scenarios",
       "A plugin built with HTML and JavaScript",
       "The Quota page"],
      "Business rules react to events such as a status change. Message scenarios only send SMS or email (Guide, Section 8)."),
    Q("INT", "mid", "A company wants to change quota values for 3 days at once from another system. Which REST API fits best?",
      ["Quota API", "Capacity API", "Metadata API", "Collaboration API"],
      "Quota API reads and updates quota. Capacity API returns available capacity and slots (Guide, Section 9)."),
    Q("INT", "mid", "Why should each connected system have its own Application (client ID and secret)?",
      ["So that you can tell which system did what, and give each system only the access it needs",
       "Because OFS allows only one connection for each client ID",
       "Because secrets expire every day",
       "Because Applications are needed for dispatcher login"],
      "One Application per system, with minimum access. Never share one secret between two systems (Guide, Sections 4 and 9)."),
    Q("OPS", "mid", "Which action goes AGAINST the best practices in the guide?",
      ["Making a small quota change directly in Production without testing it or writing it down",
       "Changing in Test first and then repeating the change in Production",
       "Keeping a change log for configuration, quota and routing changes",
       "Using a fixed naming pattern for types, skills and zones"],
      "Test first and document every change (Guide, Section 11)."),

    # ---------------- SCENARIO (10) ----------------
    Q("ROLE", "scenario", "At 11 AM a technician reaches a house, but nobody is at home. Based on the roles, who does what next?",
      ["The technician marks the activity Not Done with a reason; the dispatcher reschedules it and informs the customer of the new window",
       "The administrator moves the activity in the Dispatch Console and informs the customer",
       "The customer marks the activity Cancelled from the mobile app",
       "The technician deletes the activity and the administrator creates a new work order"],
      "PPT slides 15 and 27: Not Done with a reason, then the dispatcher handles the change."),
    Q("TERM", "scenario", "A customer says 'AC is not cooling'. The support team records 'Repair AC and refill gas at B-24'. The dispatcher plans a visit 'Tuesday 12:00-16:00' for Tech-GZB-01 with his van, who covers the Ghaziabad service area. Which list gives the correct terms, in order?",
      ["Service request, work order, activity, resource, territory",
       "Work order, service request, activity, territory, resource",
       "Service request, activity, work order, resource, territory",
       "Work order, activity, service request, resource, territory"],
      "PPT slide 26 shows the same mapping idea: complaint, job record, visit, technician and van, service area."),
    Q("RES", "scenario", "A new technician, Tech-NOI-10, has the right skills and zones, but capacity for him is zero and no job is ever assigned. What was most likely forgotten?",
      ["The work schedule (calendar) with working days and hours",
       "The default duration of the activity type",
       "An SMS message scenario for the technician",
       "A new application for the Collaboration API"],
      "Without a calendar the technician has 0 working minutes (Guide, Section 3, common mistakes)."),
    Q("SEC", "scenario", "A new technician, Imran, logs in and sees an empty screen. His user is active and his user type allows the mobile screen. What is the next most likely cause?",
      ["His user is linked to the bucket instead of his own resource",
       "His skill ratio is 100%",
       "The time slot 12-16 was not created",
       "The quota is set to 100%"],
      "Guide, Section 4, real case: after linking the correct resource, Imran saw his route."),
    Q("WORK", "scenario", "After the nightly run, 40 Noida jobs are unassigned. All are in Sector 150 (postal code 201310). The technicians have the right skills and calendars. What is the correct fix?",
      ["Add postal code 201310 to a work zone, assign that zone to the technicians who cover it, then re-run the plan",
       "Raise the quota to 100% for all Noida slots",
       "Reduce the activity duration to 30 minutes",
       "Create a new SMS scenario for Noida customers"],
      "No zone matched the address, so OFS could not match a technician (Guide, Section 7, real case)."),
    Q("CAP", "scenario", "On 12 May the Ghaziabad 16-20 slot shows 0 minutes left at 10 AM. Capacity is 1,200 min, quota is 70% and 840 min are booked. Technicians still have free time after 18:00. What should the admin do first?",
      ["Raise the quota percentage for that slot, because the quota limit of 840 min has been reached",
       "Add more technicians, because capacity has become zero",
       "Change the routing profile, because it calculates capacity",
       "Make the time slot shorter so that fewer minutes are needed"],
      "The slot is full because bookings reached the quota, not the capacity (Guide, Section 6, Figure 8 and real case)."),
    Q("ROUT", "scenario", "On Monday morning 15 technicians have no jobs while 120 jobs wait in the bucket. Nothing was planned over the weekend. What is the most likely cause?",
      ["The nightly bulk routing plan did not run, for example its schedule was switched off during a Friday change",
       "The immediate routing run assigned jobs too fast",
       "The quota is higher than the capacity",
       "All technicians have skills at 100%"],
      "Guide, Section 10, more real cases: switch the plan on, run it manually and add a daily check."),
    Q("CONF", "scenario", "FastCool wants an SMS only for AC_REPAIR jobs when the technician starts travelling, and only if the customer phone is not empty. Which setup is correct?",
      ["Message scenario: trigger = status changes to Enroute; condition = type AC_REPAIR and phone not empty; channel = SMS",
       "Message scenario: trigger = activity created; no condition; channel = SMS",
       "Message scenario: trigger = status changes to Complete; condition = type AC_REPAIR; channel = email",
       "A plugin that sends SMS, because messages always need code"],
      "Guide, Section 8, Figure 11. A plugin is the last option and not needed here."),
    Q("INT", "scenario", "At 9 AM no new Fusion requests create jobs. The failed-message log shows '401 Unauthorized' on every call. IT rotated a secret last night. What is the correct fix?",
      ["Give the new secret from the vault to the integration team, update OIC, and re-send the failed messages",
       "Add the missing postal codes to the work zones",
       "Raise quota for all slots of the day",
       "Change the status mapping for the 'complete' status"],
      "Guide, Section 9, real case. Also write down who owns each secret and what to update when it changes."),
    Q("OPS", "scenario", "A job is unassigned. Following the guide's checklist from top to bottom: the activity has a skill, a technician has that skill above 0%, and the address matches a work zone key. But the technician does not cover that zone. What is the correct action?",
      ["Add the work zone to the technician's resource",
       "Add a skill to the activity type",
       "Add the postal code to the work zone",
       "Fix the calendar or the time slot"],
      "Step 4 of the checklist: 'Does the technician cover that work zone? If NO: add zone to resource' (Guide, Section 10)."),
]
QUESTIONS = []
for _i, _q in enumerate(_RAW, 1):
    _q["id"] = _i
    QUESTIONS.append(_q)
BY_ID = {q["id"]: q for q in QUESTIONS}

# ----------------------------- DATABASE -------------------------------------
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS attempts(
            token TEXT PRIMARY KEY, name TEXT, student_id TEXT, started_at REAL, submitted_at REAL,
            order_json TEXT, perm_json TEXT, answers_json TEXT, marked_json TEXT,
            tab_switches INTEGER DEFAULT 0, result_json TEXT)""")


def get_attempt(token):
    with db() as c:
        row = c.execute("SELECT * FROM attempts WHERE token=?", (token,)).fetchone()
    if not row:
        abort(404)
    return row


def remaining(row):
    return max(0, int(row["started_at"] + DURATION_SEC - time.time()))


# ----------------------------- GRADING --------------------------------------
def pct(a, b):
    return round(100 * a / b) if b else 0


def verdict(p):
    return "Strong" if p >= 75 else ("Average" if p >= 50 else "Weak")


def grade(row):
    order = json.loads(row["order_json"])
    perms = json.loads(row["perm_json"])
    ans = json.loads(row["answers_json"] or "{}")
    marked = json.loads(row["marked_json"] or "{}")
    topics = {k: dict(total=0, correct=0, wrong=0, skipped=0) for k in TOPICS}
    levels = {k: dict(total=0, correct=0, wrong=0, skipped=0) for k in LEVELS}
    review = []
    for n, qid in enumerate(order, 1):
        q = BY_ID[qid]
        perm = perms[str(qid)]
        pos = ans.get(str(qid))
        if isinstance(pos, int) and 0 <= pos < 4:
            status = "correct" if perm[pos] == 0 else "wrong"
            your = q["options"][perm[pos]]
        else:
            status, your = "skipped", None
        for bucket in (topics[q["topic"]], levels[q["level"]]):
            bucket["total"] += 1
            bucket[status if status != "correct" else "correct"] += 1
        review.append(dict(n=n, level=LEVELS[q["level"]], topic=TOPICS[q["topic"]][0], q=q["q"],
                           status=status, your=your, correct=q["options"][0], why=q["why"],
                           marked=bool(marked.get(str(qid)))))
    correct = sum(v["correct"] for v in topics.values())
    wrong = sum(v["wrong"] for v in topics.values())
    skipped = sum(v["skipped"] for v in topics.values())
    total = len(order)
    score = max(0.0, correct * MARK_PER_Q - wrong * NEGATIVE)
    max_score = total * MARK_PER_Q
    percent = pct(score, max_score)
    for d in list(topics.values()) + list(levels.values()):
        d["percent"] = pct(d["correct"], d["total"])
        d["verdict"] = verdict(d["percent"])
    topic_list = [dict(key=k, name=TOPICS[k][0], **v) for k, v in topics.items()]
    level_list = [dict(key=k, name=LEVELS[k], **v) for k, v in levels.items()]
    ranked = sorted(topic_list, key=lambda t: (-t["percent"], t["name"]))
    strong = [t["name"] for t in ranked if t["percent"] >= 75]
    weak = [t["name"] for t in reversed(ranked) if t["percent"] < 50]
    end = row["submitted_at"] or time.time()
    taken = int(min(max(0, end - row["started_at"]), DURATION_SEC))

    if percent >= 85: band, note = "Excellent", "You are ready to work on real Oracle Field Service projects."
    elif percent >= 70: band, note = "Good", "Your base is solid. Close the weak areas and you will be project ready."
    elif percent >= 55: band, note = "Average", "You know the basics, but need more lab practice before real projects."
    else: band, note = "Needs improvement", "Revise the core topics and repeat the labs, then try the test again."

    lv = {l["key"]: l for l in level_list}
    ins = []
    best, worst = ranked[0], ranked[-1]
    ins.append(f"Your best topic is {best['name']} ({best['percent']}%). Your weakest topic is {worst['name']} ({worst['percent']}%).")
    if lv["basic"]["percent"] < 60:
        ins.append("Basic-level accuracy is low. Revise the fundamentals first, because every other topic depends on them.")
    if lv["basic"]["percent"] >= 70 and lv["scenario"]["percent"] < 50:
        ins.append("You know the theory but find real-life scenarios difficult. Practise reading a situation, finding the setting that causes it, and removing wrong options one by one.")
    if lv["scenario"]["percent"] >= 70:
        ins.append("You score well in scenario questions, which shows good practical thinking.")
    if skipped >= 3 and NEGATIVE == 0:
        ins.append(f"You left {skipped} questions unanswered. There is no negative marking, so always attempt every question.")
    if taken < DURATION_SEC * 0.25 and percent < 60:
        ins.append("You finished very quickly. Use the available time to re-read each question and check your answers.")
    plan = [dict(topic=t["name"], percent=t["percent"], tips=TOPICS[t["key"]][1])
            for t in sorted(topic_list, key=lambda t: t["percent"]) if t["percent"] < 75][:4]
    return dict(
        name=row["name"], student_id=row["student_id"], title=TEST_TITLE,
        date=datetime.fromtimestamp(end).strftime("%d %b %Y, %I:%M %p"),
        score=round(score, 2), max_score=max_score, percent=percent, correct=correct, wrong=wrong,
        skipped=skipped, total=total, taken=taken, duration=DURATION_SEC, band=band, note=note,
        passed=percent >= PASS_PERCENT, pass_percent=PASS_PERCENT, negative=NEGATIVE,
        levels=level_list, topics=topic_list, strong=strong, weak=weak, insights=ins, plan=plan,
        review=review)


# ----------------------------- API ------------------------------------------
@app.post("/api/start")
def api_start():
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()[:80]
    sid = (d.get("student_id") or "").strip()[:40]
    if len(name) < 2:
        return jsonify(error="Please enter your full name."), 400
    order, perms = [], {}
    for lvl in LEVELS:                       # basic -> intermediate -> scenario, shuffled inside each level
        ids = [q["id"] for q in QUESTIONS if q["level"] == lvl]
        random.shuffle(ids)
        order += ids
    for q in QUESTIONS:
        p = list(range(4))
        random.shuffle(p)
        perms[str(q["id"])] = p              # p[i] = original option index shown at position i
    token = secrets.token_urlsafe(9)
    with db() as c:
        c.execute("INSERT INTO attempts(token,name,student_id,started_at,order_json,perm_json,answers_json,marked_json) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (token, name, sid, time.time(), json.dumps(order), json.dumps(perms), "{}", "{}"))
    return jsonify(token=token)


@app.get("/api/attempt/<token>")
def api_attempt(token):
    row = get_attempt(token)
    if row["submitted_at"]:
        return jsonify(error="submitted"), 409
    perms = json.loads(row["perm_json"])
    qs = []
    for qid in json.loads(row["order_json"]):
        q = BY_ID[qid]
        qs.append(dict(id=qid, topic=TOPICS[q["topic"]][0], level=q["level"], level_name=LEVELS[q["level"]],
                       q=q["q"], options=[q["options"][i] for i in perms[str(qid)]]))
    return jsonify(name=row["name"], questions=qs, answers=json.loads(row["answers_json"] or "{}"),
                   marked=json.loads(row["marked_json"] or "{}"), tab_switches=row["tab_switches"],
                   remaining=remaining(row), duration=DURATION_SEC)


def _store(row, d):
    ans = {str(k): v for k, v in (d.get("answers") or {}).items() if isinstance(v, int) and 0 <= v < 4}
    marked = {str(k): True for k, v in (d.get("marked") or {}).items() if v}
    tabs = max(row["tab_switches"], int(d.get("tab_switches") or 0))
    return json.dumps(ans), json.dumps(marked), tabs


@app.post("/api/save/<token>")
def api_save(token):
    row = get_attempt(token)
    if row["submitted_at"]:
        return jsonify(error="submitted"), 409
    if time.time() > row["started_at"] + DURATION_SEC + GRACE_SEC:
        return jsonify(error="time over"), 403
    a, m, t = _store(row, request.get_json(force=True, silent=True) or {})
    with db() as c:
        c.execute("UPDATE attempts SET answers_json=?,marked_json=?,tab_switches=? WHERE token=?", (a, m, t, token))
    return jsonify(ok=True, remaining=remaining(row))


@app.post("/api/submit/<token>")
def api_submit(token):
    row = get_attempt(token)
    if not row["submitted_at"]:
        d = request.get_json(force=True, silent=True) or {}
        a, m, t = (row["answers_json"], row["marked_json"], row["tab_switches"])
        if time.time() <= row["started_at"] + DURATION_SEC + GRACE_SEC:   # accept final answers only inside the time limit
            a, m, t = _store(row, d)
        now = time.time()
        with db() as c:
            c.execute("UPDATE attempts SET answers_json=?,marked_json=?,tab_switches=?,submitted_at=? WHERE token=?",
                      (a, m, t, now, token))
        row = get_attempt(token)
        with db() as c:
            c.execute("UPDATE attempts SET result_json=? WHERE token=?", (json.dumps(grade(row)), token))
    return jsonify(ok=True)


# ----------------------------- PAGES ----------------------------------------
@app.get("/")
def home():
    return PAGE_HOME.replace("__CSS__", CSS).replace("__TITLE__", TEST_TITLE) \
        .replace("__MIN__", str(DURATION_SEC // 60)).replace("__N__", str(len(QUESTIONS))) \
        .replace("__PASS__", str(PASS_PERCENT)) \
        .replace("__MARKING__", "No negative marking." if NEGATIVE == 0 else f"Each wrong answer cuts {NEGATIVE:g} mark.")


@app.get("/test/<token>")
def test_page(token):
    row = get_attempt(token)
    if row["submitted_at"]:
        return redirect(f"/report/{token}")
    return PAGE_TEST.replace("__CSS__", CSS).replace("__TITLE__", TEST_TITLE).replace("__TOKEN__", token)


@app.get("/report/<token>")
def report_page(token):
    row = get_attempt(token)
    if not row["submitted_at"]:
        return redirect(f"/test/{token}")
    data = json.loads(row["result_json"]) if row["result_json"] else grade(row)
    blob = json.dumps(data).replace("</", "<\\/")
    return PAGE_REPORT.replace("__CSS__", CSS).replace("__TITLE__", TEST_TITLE).replace("__DATA__", blob)


def _admin_rows():
    with db() as c:
        rows = c.execute("SELECT * FROM attempts ORDER BY started_at DESC").fetchall()
    return rows


@app.get("/admin")
def admin():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorized. Open /admin?key=YOUR_ADMIN_KEY", 401
    rows = _admin_rows()
    done = [json.loads(r["result_json"]) for r in rows if r["result_json"]]
    avg = round(sum(d["percent"] for d in done) / len(done)) if done else 0
    tavg = {}
    for d in done:
        for t in d["topics"]:
            tavg.setdefault(t["name"], []).append(t["percent"])
    topic_html = "".join(
        f"<tr><td>{n}</td><td><div class='bar'><i style='width:{round(sum(v)/len(v))}%'></i></div></td><td>{round(sum(v)/len(v))}%</td></tr>"
        for n, v in sorted(tavg.items(), key=lambda x: sum(x[1]) / len(x[1])))
    body = ""
    for r in rows:
        res = json.loads(r["result_json"]) if r["result_json"] else None
        st = "Submitted" if r["submitted_at"] else ("Time over" if remaining(r) == 0 else "In progress")
        body += (f"<tr><td>{r['name']}</td><td>{r['student_id'] or '-'}</td>"
                 f"<td>{datetime.fromtimestamp(r['started_at']).strftime('%d %b %H:%M')}</td><td>{st}</td>"
                 f"<td>{(str(res['score']) + '/' + str(res['max_score']) + ' (' + str(res['percent']) + '%)') if res else '-'}</td>"
                 f"<td>{(str(res['taken'] // 60) + ' min') if res else '-'}</td><td>{r['tab_switches']}</td>"
                 f"<td><a href='/report/{r['token']}'>Open report</a></td></tr>")
    return PAGE_ADMIN.replace("__CSS__", CSS).replace("__KEY__", ADMIN_KEY).replace("__ROWS__", body or "<tr><td colspan=8>No attempts yet.</td></tr>") \
        .replace("__TOPICS__", topic_html or "").replace("__COUNT__", str(len(rows))).replace("__DONE__", str(len(done))).replace("__AVG__", str(avg))


@app.get("/admin/export")
def admin_export():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorized", 401
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Student ID", "Started", "Score", "Max", "Percent", "Correct", "Wrong", "Skipped",
                "Time (min)", "Tab switches"] + [v[0] for v in TOPICS.values()])
    for r in _admin_rows():
        if not r["result_json"]:
            continue
        d = json.loads(r["result_json"])
        w.writerow([r["name"], r["student_id"], datetime.fromtimestamp(r["started_at"]).isoformat(" ", "minutes"),
                    d["score"], d["max_score"], d["percent"], d["correct"], d["wrong"], d["skipped"],
                    d["taken"] // 60, r["tab_switches"]] + [t["percent"] for t in d["topics"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ofs_results.csv"})


# ----------------------------- FRONT END ------------------------------------
CSS = r"""
:root{--paper:#edf0f4;--card:#fff;--ink:#17202b;--muted:#5b6877;--line:#d6dce4;--route:#1f5fd1;--route-d:#1749a3;
--flag:#e8a800;--good:#17895a;--bad:#c13a3a;--soft:#e6eefc;--r:10px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
h1,h2,h3{line-height:1.2;margin:0 0 .5em;letter-spacing:-.01em}
a{color:var(--route)}button{font:inherit;cursor:pointer}
:focus-visible{outline:3px solid var(--flag);outline-offset:2px}
.btn{border:0;border-radius:8px;padding:.7em 1.3em;font-weight:600;background:var(--route);color:#fff}
.btn:hover{background:var(--route-d)}.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.btn.ghost:hover{background:var(--soft)}.btn.warn{background:var(--flag);color:#17202b}.btn[disabled]{opacity:.5;cursor:not-allowed}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:22px}
.muted{color:var(--muted)}.tag{display:inline-block;border-radius:99px;padding:.15em .75em;font-size:.82rem;font-weight:600;background:var(--soft);color:var(--route-d)}
.tag.basic{background:#e3f4ea;color:#0f6a43}.tag.mid{background:#e6eefc;color:#1749a3}.tag.scenario{background:#fdf1d2;color:#7a5600}
.bar{height:12px;border-radius:6px;background:#e3e8ee;overflow:hidden}.bar i{display:block;height:100%;background:var(--route);border-radius:6px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.55em .6em;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:.9rem;color:var(--muted);font-weight:600}
/* home */
.home{max-width:1060px;margin:0 auto;padding:48px 20px;display:grid;grid-template-columns:1.15fr .85fr;gap:40px;align-items:start}
.home h1{font-size:2.7rem}.home .lead{font-size:1.1rem;color:var(--muted);max-width:34em}
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:26px 0}
.facts div{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:14px}
.facts b{display:block;font-size:1.7rem;color:var(--route)}
.route{height:6px;border-radius:3px;background:repeating-linear-gradient(90deg,var(--route) 0 18px,transparent 18px 28px);margin:0 0 26px;max-width:260px}
label{display:block;font-weight:600;margin:14px 0 4px}input[type=text]{width:100%;padding:.7em .8em;border:1px solid #b9c2cd;border-radius:8px;font:inherit}
ul.rules{padding-left:1.1em;color:var(--muted)}ul.rules li{margin:.3em 0}
/* test */
.top{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center;padding:10px 20px;flex-wrap:wrap}
.top .t{font-weight:700}.top .sp{flex:1}.timer{font-variant-numeric:tabular-nums;font-weight:700;font-size:1.25rem;padding:.25em .9em;border-radius:99px;background:var(--soft);color:var(--route-d)}
.timer.low{background:#fdf1d2;color:#7a5600}.timer.crit{background:#fbdcdc;color:#9b2323}
.prog{height:5px;background:#e3e8ee}.prog i{display:block;height:100%;background:var(--route);transition:width .3s}
.exam{max-width:1100px;margin:0 auto;padding:22px 20px 60px;display:grid;grid-template-columns:1fr 290px;gap:22px;align-items:start}
.qmeta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.qtext{font-size:1.2rem;font-weight:600;margin:6px 0 18px;max-width:46em}
.opt{display:flex;gap:12px;align-items:flex-start;width:100%;text-align:left;background:#fff;border:2px solid var(--line);border-radius:var(--r);padding:13px 15px;margin:0 0 10px}
.opt:hover{border-color:#9db8ea}.opt .k{flex:none;width:28px;height:28px;border-radius:50%;border:2px solid #aab5c2;display:grid;place-items:center;font-weight:700;font-size:.85rem}
.opt.sel{border-color:var(--route);background:var(--soft)}.opt.sel .k{background:var(--route);border-color:var(--route);color:#fff}
.nav{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.nav .sp{flex:1}
.pal{position:sticky;top:78px}.pal h3{font-size:1rem;margin:14px 0 8px}.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:7px}
.grid button{aspect-ratio:1;border-radius:8px;border:1.5px solid var(--line);background:#fff;font-weight:600;position:relative}
.grid button.ans{background:var(--route);border-color:var(--route);color:#fff}
.grid button.mk::after{content:"";position:absolute;top:-5px;right:-5px;width:13px;height:13px;border-radius:50%;background:var(--flag);border:2px solid #fff}
.grid button.cur{outline:3px solid var(--ink);outline-offset:1px}
.legend{display:flex;flex-wrap:wrap;gap:10px 14px;font-size:.82rem;color:var(--muted);margin-top:14px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;border:1.5px solid var(--line);vertical-align:-1px;margin-right:4px}
.modal{position:fixed;inset:0;background:rgba(23,32,43,.55);display:none;place-items:center;z-index:50;padding:16px}.modal.on{display:grid}
.modal .box{background:#fff;border-radius:14px;padding:26px;max-width:460px;width:100%}
.sum{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}.sum div{background:var(--paper);border-radius:8px;padding:10px;text-align:center}.sum b{font-size:1.5rem;display:block}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:#fff;padding:.7em 1.2em;border-radius:8px;display:none;z-index:60;max-width:90vw}
/* report */
.rep{max-width:1000px;margin:0 auto;padding:28px 20px 70px}
.hero{display:grid;grid-template-columns:200px 1fr;gap:28px;align-items:center}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:18px 0 0}.stats div{background:var(--paper);border-radius:8px;padding:10px 12px}.stats b{display:block;font-size:1.4rem}
.sec{margin-top:22px}.sec h2{font-size:1.35rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.trow{display:grid;grid-template-columns:230px 1fr 90px;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.fill{height:14px;border-radius:7px}.fill.Strong{background:var(--good)}.fill.Average{background:var(--flag)}.fill.Weak{background:var(--bad)}
.pill{font-size:.8rem;font-weight:700;border-radius:99px;padding:.1em .7em}.pill.Strong{background:#dff3e8;color:#0f6a43}.pill.Average{background:#fdf1d2;color:#7a5600}.pill.Weak{background:#fbdcdc;color:#9b2323}
.rv{border:1px solid var(--line);border-left-width:6px;border-radius:var(--r);padding:14px 16px;margin:0 0 12px;background:#fff}
.rv.correct{border-left-color:var(--good)}.rv.wrong{border-left-color:var(--bad)}.rv.skipped{border-left-color:#8c97a4}
.rv p{margin:.3em 0}.why{background:var(--paper);border-radius:8px;padding:8px 12px;margin-top:8px;font-size:.95rem}
.chips button{margin:0 6px 8px 0}.chips .on{background:var(--ink);color:#fff}
@media(max-width:860px){.home,.exam,.two,.hero{grid-template-columns:1fr}.pal{position:static}.stats{grid-template-columns:repeat(2,1fr)}.trow{grid-template-columns:1fr}.home h1{font-size:2.1rem}}
@media print{.noprint,.top{display:none!important}body{background:#fff}.card,.rv{break-inside:avoid}.rv{display:block!important}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

PAGE_HOME = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head><body>
<main class="home">
<section>
  <div class="route"></div>
  <h1>__TITLE__</h1>
  <p class="lead">Check how well you understand Oracle Field Service: dispatching, routing, capacity, mobility, integration and more. After you submit, you get a full report that shows your strong and weak topics.</p>
  <div class="facts"><div><b>__N__</b>questions</div><div><b>__MIN__ min</b>time limit</div><div><b>__PASS__%</b>to pass</div></div>
  <h3>Question mix</h3>
  <table><tr><td><span class="tag basic">Basic</span></td><td>10 questions</td><td class="muted">Concepts you must know well</td></tr>
  <tr><td><span class="tag mid">Intermediate</span></td><td>15 questions</td><td class="muted">Configuration and how features work</td></tr>
  <tr><td><span class="tag scenario">Scenario-based</span></td><td>10 questions</td><td class="muted">Real project situations</td></tr></table>
  <h3 style="margin-top:22px">Rules</h3>
  <ul class="rules"><li>Each question has one correct answer. __MARKING__</li><li>The timer runs on the server. If you refresh the page or lose internet, your answers are saved and the test continues.</li>
  <li>When time ends, the test is submitted automatically.</li><li>Switching to another tab or window is counted and shown to your trainer.</li></ul>
</section>
<section class="card">
  <h2>Start the test</h2>
  <div id="resume" style="display:none" class="card" ><p><b>You have a test in progress.</b></p><button class="btn" id="rb">Resume test</button></div>
  <label for="n">Full name</label><input type="text" id="n" autocomplete="name">
  <label for="s">Student ID or batch (optional)</label><input type="text" id="s">
  <p id="err" style="color:var(--bad);min-height:1.4em"></p>
  <button class="btn" id="go" style="width:100%">Start test</button>
  <p class="muted" style="font-size:.9rem;margin-bottom:0">The timer starts as soon as you press Start.</p>
</section></main>
<script>
const $=id=>document.getElementById(id);
const t=localStorage.getItem("ofs_token");
if(t){fetch("/api/attempt/"+t).then(r=>{if(r.ok){$("resume").style.display="block";$("rb").onclick=()=>location.href="/test/"+t}else if(r.status==409){const a=document.createElement("a");a.href="/report/"+t;a.textContent="View your last report";$("err").appendChild(a)}})}
$("go").onclick=async()=>{$("go").disabled=true;$("err").textContent="";
 const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:$("n").value,student_id:$("s").value})});
 const d=await r.json();if(!r.ok){$("err").textContent=d.error;$("go").disabled=false;return}
 localStorage.setItem("ofs_token",d.token);location.href="/test/"+d.token};
</script></body></html>"""

PAGE_TEST = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head><body>
<header class="top"><span class="t">__TITLE__</span><span class="muted" id="who"></span><span class="sp"></span>
<span class="timer" id="timer" role="timer" aria-live="off">--:--:--</span><button class="btn warn" id="sub">Submit test</button></header>
<div class="prog"><i id="pg" style="width:0"></i></div>
<main class="exam">
 <section class="card" id="qc" aria-live="polite"></section>
 <aside class="card pal"><b id="cnt"></b><div id="pal"></div>
  <div class="legend"><span><i style="background:var(--route);border-color:var(--route)"></i>Answered</span><span><i></i>Not answered</span><span><i style="background:var(--flag);border-color:var(--flag);border-radius:50%"></i>Marked</span></div>
  <p class="muted" style="font-size:.82rem;margin:14px 0 0">Keys: 1-4 choose, M mark, Left/Right move.</p></aside>
</main>
<div class="modal" id="md"><div class="box"><h2>Submit your test?</h2><div class="sum" id="sm"></div>
 <p class="muted" id="warn"></p><div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn ghost" id="bk">Go back</button><button class="btn" id="ok">Submit now</button></div></div></div>
<div class="toast" id="ts"></div>
<script>
const TOKEN="__TOKEN__",$=id=>document.getElementById(id);
const S={qs:[],ans:{},mk:{},cur:0,end:0,tabs:0,done:false};let timerFix=null;
const L="ABCD";
async function load(){const r=await fetch("/api/attempt/"+TOKEN);if(r.status==409){location.href="/report/"+TOKEN;return}
 const d=await r.json();S.qs=d.questions;S.ans=d.answers;S.mk=d.marked;S.tabs=d.tab_switches;S.end=Date.now()+d.remaining*1000;$("who").textContent=d.name;
 const first=S.qs.findIndex(q=>S.ans[q.id]===undefined);S.cur=first<0?0:first;draw();tick();setInterval(tick,1000);setInterval(save,30000)}
function pad(n){return String(n).padStart(2,"0")}
function tick(){if(S.done)return;const s=Math.max(0,Math.round((S.end-Date.now())/1000));
 $("timer").textContent=pad(Math.floor(s/3600))+":"+pad(Math.floor(s%3600/60))+":"+pad(s%60);
 $("timer").className="timer"+(s<300?" crit":s<900?" low":"");if(s<=0)finish(true)}
function draw(){drawQ();drawPal()}
function drawQ(){const q=S.qs[S.cur];if(!q)return;const sel=S.ans[q.id];
 let h=`<div class="qmeta"><b>Question ${S.cur+1} of ${S.qs.length}</b><span class="tag ${q.level}">${q.level_name}</span><span class="tag">${esc(q.topic)}</span></div><p class="qtext">${esc(q.q)}</p>`;
 q.options.forEach((o,i)=>{h+=`<button class="opt ${sel===i?"sel":""}" data-i="${i}" aria-pressed="${sel===i}"><span class="k">${L[i]}</span><span>${esc(o)}</span></button>`});
 h+=`<div class="nav"><button class="btn ghost" id="pv" ${S.cur==0?"disabled":""}>Previous</button><button class="btn ghost" id="mk">${S.mk[q.id]?"Remove mark":"Mark for review"}</button><button class="btn ghost" id="cl" ${sel===undefined?"disabled":""}>Clear answer</button><span class="sp"></span><button class="btn" id="nx" ${S.cur==S.qs.length-1?"disabled":""}>Save &amp; next</button></div>`;
 $("qc").innerHTML=h;$("qc").querySelectorAll(".opt").forEach(b=>b.onclick=()=>pick(+b.dataset.i));
 $("pv").onclick=()=>go(S.cur-1);$("nx").onclick=()=>go(S.cur+1);$("mk").onclick=mark;$("cl").onclick=clr;
 const a=Object.keys(S.ans).length;$("pg").style.width=(100*a/S.qs.length)+"%"}
function drawPal(){let h="",last="";S.qs.forEach((q,i)=>{if(q.level!==last){last=q.level;h+=(i?"</div>":"")+`<h3>${q.level_name}</h3><div class="grid">`}
 h+=`<button class="${S.ans[q.id]!==undefined?"ans":""} ${S.mk[q.id]?"mk":""} ${i==S.cur?"cur":""}" data-i="${i}" aria-label="Question ${i+1}">${i+1}</button>`});
 $("pal").innerHTML=h+"</div>";$("pal").querySelectorAll("button").forEach(b=>b.onclick=()=>go(+b.dataset.i));
 $("cnt").textContent=Object.keys(S.ans).length+" of "+S.qs.length+" answered"}
function esc(s){return s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function go(i){if(i<0||i>=S.qs.length)return;S.cur=i;draw();window.scrollTo({top:0})}
function pick(i){S.ans[S.qs[S.cur].id]=i;draw();saveSoon()}
function clr(){delete S.ans[S.qs[S.cur].id];draw();saveSoon()}
function mark(){const id=S.qs[S.cur].id;if(S.mk[id])delete S.mk[id];else S.mk[id]=true;draw();saveSoon()}
function body(){return JSON.stringify({answers:S.ans,marked:S.mk,tab_switches:S.tabs})}
function saveSoon(){clearTimeout(timerFix);timerFix=setTimeout(save,500)}
async function save(){if(S.done)return;try{const r=await fetch("/api/save/"+TOKEN,{method:"POST",headers:{"Content-Type":"application/json"},body:body()});
 if(r.status==409)location.href="/report/"+TOKEN}catch(e){toast("No internet. Your answers will be saved when the connection returns.")}}
function toast(m){const t=$("ts");t.textContent=m;t.style.display="block";clearTimeout(t._h);t._h=setTimeout(()=>t.style.display="none",4000)}
$("sub").onclick=()=>{const a=Object.keys(S.ans).length,m=Object.keys(S.mk).length,u=S.qs.length-a;
 $("sm").innerHTML=`<div><b>${a}</b>answered</div><div><b>${u}</b>not answered</div><div><b>${m}</b>marked</div>`;
 $("warn").textContent=u?"You still have unanswered questions. After you submit, you cannot change any answer.":"After you submit, you cannot change any answer.";$("md").classList.add("on")};
$("bk").onclick=()=>$("md").classList.remove("on");$("ok").onclick=()=>finish(false);
async function finish(auto){if(S.done)return;S.done=true;$("ok").disabled=true;
 try{await fetch("/api/submit/"+TOKEN,{method:"POST",headers:{"Content-Type":"application/json"},body:body()})}catch(e){S.done=false;$("ok").disabled=false;toast("Could not submit. Check your internet and try again.");return}
 location.href="/report/"+TOKEN}
document.addEventListener("visibilitychange",()=>{if(document.hidden&&!S.done){S.tabs++;saveSoon();toast("You left the test tab. This is recorded ("+S.tabs+").")}});
document.addEventListener("keydown",e=>{if(e.target.tagName==="INPUT"||$("md").classList.contains("on"))return;
 if("1234".includes(e.key)&&e.key)pick(+e.key-1);else if(e.key==="ArrowRight")go(S.cur+1);else if(e.key==="ArrowLeft")go(S.cur-1);else if(e.key==="m"||e.key==="M")mark()});
window.addEventListener("beforeunload",e=>{if(!S.done){e.preventDefault();e.returnValue=""}});
load();
</script></body></html>"""

PAGE_REPORT = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Result - __TITLE__</title><style>__CSS__</style></head><body>
<main class="rep" id="app"></main>
<script>
const D=__DATA__;const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const col=v=>v=="Strong"?"var(--good)":v=="Average"?"var(--flag)":"var(--bad)";
const mins=s=>Math.floor(s/60)+" min "+String(s%60).padStart(2,"0")+" sec";
function ring(p){const r=80,c=2*Math.PI*r,v=p>=75?"var(--good)":p>=50?"var(--flag)":"var(--bad)";
 return `<svg viewBox="0 0 200 200" width="200" height="200" role="img" aria-label="Score ${p} percent"><circle cx="100" cy="100" r="${r}" fill="none" stroke="#e3e8ee" stroke-width="18"/>
 <circle cx="100" cy="100" r="${r}" fill="none" stroke="${v}" stroke-width="18" stroke-linecap="round" stroke-dasharray="${c*p/100} ${c}" transform="rotate(-90 100 100)"/>
 <text x="100" y="104" text-anchor="middle" font-size="46" font-weight="700" fill="#17202b">${p}%</text><text x="100" y="130" text-anchor="middle" font-size="14" fill="#5b6877">${D.score} / ${D.max_score}</text></svg>`}
function radar(){const n=D.topics.length,cx=220,cy=170,R=120;const pt=(i,v)=>{const a=-Math.PI/2+2*Math.PI*i/n;return [cx+R*v/100*Math.cos(a),cy+R*v/100*Math.sin(a)]};
 let g="";[25,50,75,100].forEach(l=>{g+=`<polygon points="${D.topics.map((_,i)=>pt(i,l).join(",")).join(" ")}" fill="none" stroke="#d6dce4"/>`});
 D.topics.forEach((t,i)=>{const [x,y]=pt(i,100),[lx,ly]=pt(i,122);g+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#d6dce4"/>`;
  const short=t.name.split(/[ &,]+/)[0];g+=`<text x="${lx}" y="${ly+4}" font-size="11" text-anchor="${lx<cx-5?"end":lx>cx+5?"start":"middle"}" fill="#5b6877">${esc(short)}</text>`});
 g+=`<polygon points="${D.topics.map((t,i)=>pt(i,t.percent).join(",")).join(" ")}" fill="rgba(31,95,209,.22)" stroke="#1f5fd1" stroke-width="2.5"/>`;
 D.topics.forEach((t,i)=>{const [x,y]=pt(i,t.percent);g+=`<circle cx="${x}" cy="${y}" r="4" fill="#1f5fd1"/>`});
 return `<svg viewBox="0 0 440 340" width="100%" role="img" aria-label="Topic radar chart">${g}</svg>`}
function build(){let h=`<div class="noprint" style="display:flex;gap:10px;justify-content:space-between;margin-bottom:14px"><a href="/" class="btn ghost" style="text-decoration:none">Home</a><button class="btn" onclick="print()">Download / print report</button></div>
<section class="card"><div class="hero"><div>${ring(D.percent)}</div><div>
<p class="muted" style="margin:0">${esc(D.title)} &middot; ${esc(D.date)}</p><h1 style="margin:.1em 0">${esc(D.name)}${D.student_id?` <span class="muted" style="font-size:1rem">(${esc(D.student_id)})</span>`:""}</h1>
<h2 style="color:${D.percent>=75?"var(--good)":D.percent>=50?"#9a6b00":"var(--bad)"}">${D.band} &ndash; ${D.passed?"Passed":"Not passed"} (pass mark ${D.pass_percent}%)</h2><p>${esc(D.note)}</p></div></div>
<div class="stats"><div><b style="color:var(--good)">${D.correct}</b>Correct</div><div><b style="color:var(--bad)">${D.wrong}</b>Wrong</div><div><b>${D.skipped}</b>Not answered</div><div><b>${Math.round(100*D.correct/Math.max(1,D.correct+D.wrong))}%</b>Accuracy (attempted)</div><div><b style="font-size:1.05rem">${mins(D.taken)}</b>Time used</div></div></section>
<section class="sec two"><div class="card"><h2>Topic radar</h2>${radar()}</div>
<div class="card"><h2>Level-wise result</h2>${D.levels.map(l=>`<div style="margin:0 0 16px"><div style="display:flex;justify-content:space-between"><b>${l.name}</b><span>${l.correct}/${l.total} &middot; ${l.percent}%</span></div><div class="bar"><i style="width:${l.percent}%;background:${col(l.verdict)}"></i></div></div>`).join("")}
<h3 style="margin-top:20px">What this means</h3><ul style="padding-left:1.1em;margin:0">${D.insights.map(i=>`<li style="margin:.4em 0">${esc(i)}</li>`).join("")}</ul></div></section>
<section class="sec card"><h2>Topic-wise performance</h2><p class="muted">Strong: 75% or more &nbsp;|&nbsp; Average: 50% to 74% &nbsp;|&nbsp; Weak: below 50%</p>
${[...D.topics].sort((a,b)=>b.percent-a.percent).map(t=>`<div class="trow"><b>${esc(t.name)}</b><div class="bar"><div class="fill ${t.verdict}" style="width:${Math.max(t.percent,2)}%"></div></div><span><span class="pill ${t.verdict}">${t.verdict}</span> ${t.correct}/${t.total}</span></div>`).join("")}</section>
<section class="sec two"><div class="card"><h2 style="color:var(--good)">Strong topics</h2>${D.strong.length?`<ul style="padding-left:1.1em;margin:0">${D.strong.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>`:`<p class="muted">No topic reached 75% yet. Keep practising.</p>`}</div>
<div class="card"><h2 style="color:var(--bad)">Topics that need attention</h2>${D.weak.length?`<ul style="padding-left:1.1em;margin:0">${D.weak.map(s=>`<li>${esc(s)}</li>`).join("")}</ul>`:`<p class="muted">No topic is below 50%. Good work.</p>`}</div></section>
${D.plan.length?`<section class="sec card"><h2>Your study plan</h2><p class="muted">Start from the lowest topic.</p>${D.plan.map(p=>`<div style="margin:0 0 14px"><b>${esc(p.topic)}</b> <span class="pill ${p.percent<50?"Weak":"Average"}">${p.percent}%</span><ul style="margin:.3em 0 0;padding-left:1.1em">${p.tips.map(t=>`<li>${esc(t)}</li>`).join("")}</ul></div>`).join("")}</section>`:""}
<section class="sec"><h2>Question review</h2><div class="chips noprint"><button class="btn ghost on" data-f="all">All (${D.total})</button><button class="btn ghost" data-f="wrong">Wrong (${D.wrong})</button><button class="btn ghost" data-f="skipped">Not answered (${D.skipped})</button><button class="btn ghost" data-f="correct">Correct (${D.correct})</button></div><div id="rv"></div></section>`;
 $("app").innerHTML=h;
 const draw=f=>{$("rv").innerHTML=D.review.filter(r=>f=="all"||r.status==f).map(r=>`<article class="rv ${r.status}"><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><b>Q${r.n}</b><span class="tag">${esc(r.level)}</span><span class="tag">${esc(r.topic)}</span><b style="margin-left:auto;color:${r.status=="correct"?"var(--good)":r.status=="wrong"?"var(--bad)":"var(--muted)"}">${r.status=="correct"?"Correct":r.status=="wrong"?"Wrong":"Not answered"}</b></div>
 <p><b>${esc(r.q)}</b></p>${r.status!="correct"?`<p><span class="muted">Your answer:</span> ${r.your?esc(r.your):"<i>No answer</i>"}</p>`:""}<p><span class="muted">Correct answer:</span> <b>${esc(r.correct)}</b></p><div class="why">${esc(r.why)}</div></article>`).join("")||"<p class='muted'>Nothing to show here.</p>"};
 draw("all");document.querySelectorAll(".chips button").forEach(b=>b.onclick=()=>{document.querySelectorAll(".chips button").forEach(x=>x.classList.remove("on"));b.classList.add("on");draw(b.dataset.f)})}
build();
</script></body></html>"""

PAGE_ADMIN = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trainer dashboard</title><style>__CSS__</style></head><body><main class="rep">
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h1>Trainer dashboard</h1><a class="btn" style="text-decoration:none" href="/admin/export?key=__KEY__">Download CSV</a></div>
<div class="stats" style="grid-template-columns:repeat(3,1fr)"><div><b>__COUNT__</b>Attempts started</div><div><b>__DONE__</b>Submitted</div><div><b>__AVG__%</b>Average score</div></div>
<section class="sec card"><h2>Average by topic (all students)</h2><table>__TOPICS__</table></section>
<section class="sec card" style="overflow:auto"><h2>All attempts</h2><table><tr><th>Name</th><th>ID</th><th>Started</th><th>Status</th><th>Score</th><th>Time</th><th>Tab switches</th><th></th></tr>__ROWS__</table></section>
</main></body></html>"""

init_db()

if __name__ == "__main__":
    print(f"\n  Student page : http://localhost:5000\n  Trainer page : http://localhost:5000/admin?key={ADMIN_KEY}\n")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
