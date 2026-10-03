#!/usr/bin/env python3
"""Otto i18n — every string a CLIENT receives, in one place: e-mails (approval digest, morning report, recommendations, the
paid-plan card, trial reminders), the one-tap confirm / done / used / expired pages, and the Telegram cards, report and
alerts. Owner-facing tools (console, CLI output, logs, owner cards) and the app UI (index.html: a research decision) stay
English and do not come through here.

  otto_i18n.py check                         # catalog completeness (every en key in nl and de, same placeholders, plurals,
                                             # both German registers) — the same rules as tests/test_i18n.py
  otto_i18n.py show <brand>                  # the language and register a brand's messages use, with samples
  otto_i18n.py lang <brand> en|nl|de         # brands[].comms_lang by hand (the client: onboarding / Settings; the owner: console)
  otto_i18n.py address <brand> formal|informal|auto      # German "Sie" / "du" for this brand (brands[].address)

Language: brands[].comms_lang — "en" | "nl" | "de", set explicitly by the client (onboarding's Connect step, the app's
Settings) or the owner (console drill-down). Missing or anything else → English, for every brand, new or old: it is never
inferred from the brand's content language, country or site (a Dutch café's POSTS are Dutch — ap.brand_lang, unchanged —
while what Otto sends the owner is English until they choose otherwise). A one-tap page whose link names no brand is English.
Per brand, not per approver: the report and decisions are about the brand, co-approvers forward and compare the same e-mail,
and Telegram is one chat per instance; e-mails are rendered per recipient, so a per-person override can come later.
English is the reference catalog: a key missing in nl / de falls back to English at runtime (and fails the completeness test).
Register (German only; Dutch messages always use the informal "je" that Dutch SMB owners expect): brands[].address =
"formal" | "Sie" → Sie, "informal" | "du" → du; missing / "auto" → the brand's own voice decides: when the site scan's text
addresses its customers with du/dein/dich clearly more than with Sie/Ihr/Ihnen, du; otherwise Sie (the B2B default).
Catalog values: a string; {"one": …, "other": …} for a count (n == 1 → one; 0 and the rest → other); German may hold
{"Sie": …, "du": …} around either. Placeholders are str.format fields; {n} is the count, formatted for the locale.
Formatting: dates ("do 6 nov · 07:35", "Do., 6. Nov. · 07:35", "Thu 6 Nov · 07:35"), numbers ("1.234,50" / "1,234.50"),
money ("€ 1.234,50" NL, "1.234,50 €" DE, "€1,234.50" EN — the space is a no-break space so a price never wraps), percent.
Stdlib only.
"""
import re, string, sys
from datetime import date, datetime

import ap

LANGS = ("en", "nl", "de")
DEFAULT = "en"
NBSP = " "
FORMAL, INFORMAL = "formal", "informal"
REGISTER_KEYS = {FORMAL: "Sie", INFORMAL: "du"}

# ---------------------------------------------------------------------------------------------------------------- locale

FMT = {
    "en": {"days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           "days_long": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
           "months_long": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                           "November", "December"],
           "day": "{wd} {d} {mon}", "day_long": "{wdl} {d} {monl}", "day_month": "{d} {mon}", "day_at": "{day}, {time}",
           "dec": ".", "grp": ",", "money": "{sym}{num}", "money_code": "{code}" + NBSP + "{num}", "pct": "{num}%",
           "and": "and"},
    "nl": {"days": ["ma", "di", "wo", "do", "vr", "za", "zo"],
           "days_long": ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"],
           "months": ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"],
           "months_long": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
                           "november", "december"],
           "day": "{wd} {d} {mon}", "day_long": "{wdl} {d} {monl}", "day_month": "{d} {mon}", "day_at": "{day} om {time}",
           "dec": ",", "grp": ".", "money": "{sym}" + NBSP + "{num}", "money_code": "{code}" + NBSP + "{num}", "pct": "{num}%",
           "and": "en"},
    "de": {"days": ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."],
           "days_long": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
           "months": ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."],
           "months_long": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                           "November", "Dezember"],
           "day": "{wd}, {d}. {mon}", "day_long": "{wdl}, {d}. {monl}", "day_month": "{d}. {mon}",
           "day_at": "{day} um {time} Uhr",
           "dec": ",", "grp": ".", "money": "{num}" + NBSP + "{sym}", "money_code": "{num}" + NBSP + "{code}",
           "pct": "{num}" + NBSP + "%", "and": "und"},
}
SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$", "ILS": "₪", "JPY": "¥"}
# zoneinfo keys say "Vienna"; a Dutch or German client reads "Wenen" / "Wien"
CITIES = {"Vienna": {"de": "Wien", "nl": "Wenen"}, "Brussels": {"de": "Brüssel", "nl": "Brussel"},
          "Zurich": {"de": "Zürich", "nl": "Zürich"}, "Luxembourg": {"de": "Luxemburg", "nl": "Luxemburg"},
          "Rome": {"de": "Rom"}, "Lisbon": {"de": "Lissabon", "nl": "Lissabon"}, "Prague": {"de": "Prag", "nl": "Praag"},
          "Warsaw": {"de": "Warschau", "nl": "Warschau"}, "Copenhagen": {"de": "Kopenhagen", "nl": "Kopenhagen"},
          "London": {"nl": "Londen"}, "Athens": {"de": "Athen", "nl": "Athene"}, "Bucharest": {"de": "Bukarest", "nl": "Boekarest"},
          "Paris": {"nl": "Parijs"}, "Madrid": {}, "Berlin": {"nl": "Berlijn"}, "Jerusalem": {}, "New York": {}}

# ---------------------------------------------------------------------------------------------------------------- catalogs
# English is the reference. Dutch: informal "je", the way Dutch SMB owners write to each other. German: "Sie" for B2B by
# default, "du" when the brand speaks du (see the module doc) — every sentence that addresses the reader has both.

EN = {
    # shared
    "fmt.reel": "Reel", "fmt.story": "Story", "fmt.carousel": "Carousel", "fmt.video": "Video",
    "btn.approve": "Approve", "btn.skip": "Skip", "btn.change": "Change", "btn.not_now": "Not now", "btn.open_otto": "Open Otto",
    "btn.approve_plan": "Approve plan", "btn.review_all": "Review all in the app", "btn.see_in_app": "See it in the app",
    "btn.open_in_app_instead": "Open in the app instead",
    "lbl.image": "Image", "img.alt": "Image: {hook}",
    "tz.times": "Times are {city} time.", "tz.label": " {city} time",
    "prio.P0": "Urgent", "prio.P1": "Recommended",
    "noun.post": {"one": "1 post", "other": "{n} posts"},
    "noun.decision": {"one": "1 decision", "other": "{n} decisions"},
    # e-mail footer
    "email.why": "You get this because you approve posts for {name} in Otto.",
    "email.settings": "Settings",
    "email.settings_sentence": "Choose how approvals reach you in {settings}.",
    "email.settings_text": "Choose how approvals reach you: {url}",
    "email.buttons_once": "Each button works once and expires after 72 hours; nothing publishes without your OK.",
    "email.links_once": "Each link works once and expires after 72 hours; nothing publishes without your OK.",
    # approval digest
    "digest.subject": {"one": "1 post to approve for {name}", "other": "{n} posts to approve for {name}"},
    "digest.subject_from": " · from {day}",
    "digest.title": {"one": "1 post needs your OK", "other": "{n} posts need your OK"},
    "digest.lead": "Tap {approve} and it goes out at its time. {skip} and Otto fills the slot. {change} opens the post in the app.",
    "digest.why": "Why this post: {why}",
    "digest.more": {"one": "1 more post is waiting in the app.", "other": "{n} more posts are waiting in the app."},
    # recommendations
    "recs.subject_one": "Otto recommends: {title}",
    "recs.subject_many": {"one": "1 recommendation for {name}", "other": "{n} recommendations for {name}"},
    "recs.title_one": "Otto recommends",
    "recs.title_many": {"one": "1 thing to decide", "other": "{n} things to decide"},
    "recs.lead": "Your agency's suggestions for this week. Approve one and Otto gets on with it; Not now puts it away.",
    "recs.impact": "Impact: {impact}",
    # the paid-plan card
    "plan.title": "Approve the {month} paid plan",
    "plan.summary": {"one": "1 campaign, ≈{total}", "other": "{n} campaigns, ≈{total}"},
    "plan.lead": "Nothing spends until you approve, and every campaign has a daily ceiling.",
    "plan.per_day": "{amount}/day",
    "plan.max_day": "up to {amount} a day",
    "plan.dates": "{start} to {end}",
    "plan.hold": " · on hold for a copy review",
    "plan.more": "and {n} more in the app",
    # one-tap pages
    "page.invalid.title": "This link doesn't work",
    "page.invalid.text": "It may have been cut short when it was copied. Open the e-mail again and tap the button, or review the post in the app.",
    "page.expired.title": "This link has expired",
    "page.expired.text": "Buttons in approval e-mails work for 72 hours. The post is still waiting for you in the app.",
    "page.used.title": "This link was already used",
    "page.used.text": "Each button works once. {result}",
    "page.denied.title": "This link can't be used any more",
    "page.denied.text": "It was sent to someone who no longer approves for this brand, or the item has moved. Open the app to see what's waiting.",
    "page.form.title": "Please tap the button again",
    "page.form.text": "This page was open for a while, so Otto asks once more. Open the link from your e-mail again.",
    "page.origin.title": "That didn't come from Otto's page",
    "page.origin.text": "For your safety, decisions are only taken from Otto's own confirmation page. Open the link from your e-mail again.",
    "page.rate.title": "Too many taps",
    "page.rate.text": "Please wait a minute and try again.",
    "page.config.title": "Otto can't check this link right now",
    "page.config.text": "Please try again in a few minutes, or review the post in the app.",
    "page.nothing.title": "Nothing to do here",
    "page.nothing.text": "{why} You can change it in the app.",
    "page.expires": "This button works once. The link expires {day}, {time}{tz}.",
    "late.post.approved": "This post is already approved.",
    "late.post.scheduled": "This post is already scheduled.",
    "late.post.skipped": "This post is already skipped.",
    "late.post.published": "This post is already published.",
    "late.post.publishing": "This post is already being published.",
    "late.post.failed": "This post is already waiting for a new slot.",
    "late.post.other": "This post is already {status}.",
    "late.rec.done": "This was already handled.",
    "late.rec.approved": "This was already approved.",
    "late.rec.dismissed": "This was already put away.",
    "late.rec.other": "This was already {status}.",
    "confirm.post.approve.title": "Approve this post?", "confirm.post.approve.btn": "Approve post",
    "confirm.post.skip.title": "Skip this post?", "confirm.post.skip.btn": "Skip post",
    "confirm.rec.approve.title": "Approve this?", "confirm.rec.approve.btn": "Approve",
    "confirm.rec.dismiss.title": "Put this away for now?", "confirm.rec.dismiss.btn": "Not now",
    "confirm.plan.title": "Approve the {month} paid plan?", "confirm.plan.btn": "Approve the plan",
    "confirm.post.approve.lead": "It goes out at its time on {platform}.",
    "confirm.page_fallback": "the page",
    "confirm.post.skip.lead": "Otto fills the slot with something else.",
    "confirm.plan.lead": "Nothing spends until you approve; every campaign keeps its daily ceiling.",
    "confirm.rec.approve.lead": "Otto gets on with it.",
    "confirm.rec.dismiss.lead": "Otto puts it away. You can bring it back in the app.",
    "done.approved.title": "Approved",
    "done.post.goes_out": "It goes out {when}.",
    "done.post.passed": "Its time has passed, so Otto will offer a new slot.",
    "done.skipped.title": "Skipped",
    "done.put_away.title": "Put away for now",
    "done.put_away.text": "You can bring it back in the app whenever you like.",
    "done.failed.title": "Approved, not started yet",
    "done.failed.text": "Your approval is saved, but Otto could not start it just now. Otto's team has been told and will finish it; nothing spends meanwhile.",
    "done.plan.text": {"one": "1 campaign approved for {month}. It starts on its date with its daily ceiling.",
                       "other": "{n} campaigns approved for {month}. Each campaign starts on its date with its daily ceiling."},
    "done.rec.text": "Done: {result}.",
    "done.rec.paused": "the campaign is paused",
    "result.approved_on": "Approved on {day}, {time}.",
    "result.skipped_on": "Skipped on {day}, {time}.",
    "result.put_away_on": "Put away on {day}, {time}.",
    # the morning report
    "report.subject": "Morning report {day} · {name}",
    "report.subject_waiting": {"one": "1 to approve", "other": "{n} to approve"},
    "report.subject_clear": "nothing needs you",
    "report.title": "Morning report",
    "report.greeting": "Good morning.",
    "report.sum.paid": "Yesterday: {spend} on ads, {results}.",
    "report.sum.no_results": "no results yet",
    "report.sum.organic": {"one": "Yesterday 1 post went out.", "other": "Yesterday {n} posts went out."},
    "report.sum.organic_reach": {"one": "Yesterday 1 post went out and reached {reach} people.",
                                 "other": "Yesterday {n} posts went out and reached {reach} people."},
    "report.sum.quiet": "Nothing went out yesterday.",
    "report.sum.starting": "Your first posts are on their way.",
    "report.sum.waiting": {"one": "1 post is waiting for your tap.", "other": "{n} posts are waiting for your tap."},
    "report.sum.decisions": {"one": "1 decision is waiting for you.", "other": "{n} decisions are waiting for you."},
    "report.sum.both": "{posts} and {decisions} are waiting for you.",
    "report.sum.clear": "Nothing needs you today.",
    "report.yesterday": "Yesterday",
    "report.sub.meta": "Meta ads and posts", "report.sub.ads": "Ads and posts", "report.sub.posts": "Your posts",
    "report.paid": "Paid ads",
    "report.posts_y": "Yesterday's posts",
    "report.waiting": "Waiting for you",
    "report.today": "Today",
    "report.today_none": "Nothing is scheduled for today.",
    "report.today_done": "already out",
    "report.best_post": "Best yesterday",
    "report.best_ad": "Best ad: “{name}”, {cost}.",
    "report.month": "This month so far: {spent} of {planned} planned.",
    "report.messages": {"one": "1 person started a chat from your ads.", "other": "{n} people started a chat from your ads."},
    "report.failed": {"one": "1 post didn't go out; the details are in the app.",
                      "other": "{n} posts didn't go out; the details are in the app."},
    "report.none_yesterday": "Nothing went out yesterday.",
    "report.first_post": "Your first post goes out {day} at {time}; its numbers show up here the morning after.",
    "report.cost_line.leads": "Cost per enquiry yesterday: {cost}.", "report.cost_line.purchases": "Cost per sale yesterday: {cost}.",
    "report.cost_line.conversions": "Cost per conversion yesterday: {cost}.", "report.cost_line.results": "Cost per result yesterday: {cost}.",
    "report.first_pending": "Your first post is ready for {day} at {time}: approve it below and its numbers show up here the morning after.",
    "report.today_waiting": "waiting for your OK",
    "report.first_none": "Your first posts are being prepared; their numbers show up here the morning after they go out.",
    "report.drop": "Heads-up: {metric} down to {value} (7-day average {avg}).",
    "report.paid.trial": "Your paid ads are planned for preview. They start once you choose a plan; nothing is spent during your trial.",
    "report.paid.not_connected": "Connect your Meta ad account in Otto to see what your ads cost and bring in.",
    "report.paid.pending": "Yesterday's ad numbers aren't in yet; they'll be in tomorrow's report.",
    "report.paid.idle": "No paid campaigns ran yesterday.",
    "report.paid.next": "Next campaign starts {day}.",
    "report.why": "You get this every morning at 07:35 because you approve posts for {name} in Otto.",
    "report.settings_sentence": "Choose how reports and approvals reach you in {settings}.",
    "report.settings_text": "Choose how reports and approvals reach you: {url}",
    "kpi.spent": "Spent", "kpi.leads": "Enquiries", "kpi.purchases": "Sales", "kpi.conversions": "Conversions",
    "kpi.results": "Results", "kpi.reach": "Reached", "kpi.clicks": "Clicks", "kpi.reactions": "Reactions",
    "kpi.within_budget": "within your {budget} daily budget",
    "kpi.over_budget": "{budget} daily budget; Meta evens it out over the week",
    "kpi.avg7": "7-day average {avg}",
    "kpi.of_posts": {"one": "from 1 post", "other": "from {n} posts"},
    "chart.per_day": "{label} per day", "chart.spend": "Spend per day",
    "res.leads": {"one": "1 enquiry", "other": "{n} enquiries"},
    "res.purchases": {"one": "1 sale", "other": "{n} sales"},
    "res.conversions": {"one": "1 conversion", "other": "{n} conversions"},
    "res.engagements": {"one": "1 engagement", "other": "{n} engagements"},
    "res.landing": {"one": "1 page view", "other": "{n} page views"},
    "cost.leads": "{cost} per enquiry", "cost.purchases": "{cost} per sale", "cost.conversions": "{cost} per conversion",
    "cost.results": "{cost} per result",
    "m.reach": "{n} reached",
    "m.clicks": {"one": "1 click", "other": "{n} clicks"},
    "m.reactions": {"one": "1 reaction", "other": "{n} reactions"},
    "m.saves": {"one": "1 save", "other": "{n} saves"},
    "m.pending": "Numbers follow in tomorrow's report.",
    "metric.reach": "reach", "metric.clicks": "clicks", "metric.saves": "saves", "metric.followers": "followers",
    "metric.leads": "enquiries", "metric.page_reach_week": "weekly page reach",
    # Telegram
    "tg.approve": "✅ Approve", "tg.skip": "❌ Skip", "tg.edit": "✏️ Edit", "tg.later": "↷ Later", "tg.not_now": "Not now",
    "tg.rec_head": "💡 Your agency recommends · {prio}",
    "tg.not_yours": "Not your Otto.",
    "tg.unknown_post": "Unknown post", "tg.unknown_rec": "Unknown recommendation",
    "tg.already": "Already {state}",
    "status.approved": "approved", "status.scheduled": "scheduled", "status.skipped": "skipped",
    "status.published": "published", "status.publishing": "being published", "status.failed": "failed",
    "status.draft": "in draft", "status.pending_approval": "waiting", "status.proposed": "proposed",
    "status.dismissed": "put away", "status.done": "done",
    "tg.note.approve": "✅ Approved · publishes {when}",
    "tg.note.skip": "❌ Skipped — Otto refills the slot",
    "tg.note.later": "↷ Later — you'll get it again tomorrow morning",
    "tg.rec.on_it": "✅ Approved — on it",
    "tg.rec.failed": "✅ Approved, not started yet — the team is on it",
    "tg.rec.approved": "✅ Approved",
    "tg.rec.dismissed": "Dismissed",
    "tg.rec.tail_done": "✅ Approved — {result}",
    "tg.rec.tail_failed": "✅ Approved — not started yet: it failed, the team has been told",
    "tg.rec.tail_dismissed": "— Not now",
    "tg.edit.answer": "Reply with the change you want",
    "tg.edit.prompt": "✏️ {pid} — reply to THIS message with what to change (e.g. “shorter, mention the lab tests”). Quill rewrites and sends a new card. (Open for 2 hours.)",
    "tg.edit.expired": "That edit prompt for {pid} expired (2 h). Tap ✏️ Edit on the card again.",
    "tg.edit.got_it": "Got it — Quill is rewriting {pid}: “{note}”. New card shortly.",
    "tg.edit.too_late": "{pid} is already {state} — edit not applied.",
    "tg.cards": {"one": "1 post: tap ✅ Approve on its card", "other": "{n} posts: tap ✅ Approve on their cards"},
    "tg.open": "Open Otto: {url}",
    # alerts (otto_watch)
    "alert.head": "Otto alert",
    "alert.drop": "Drop at {brand}: {metric} is at {value}, {pct}%+ below the 7-day average ({avg}). Worth a look.",
    "alert.stuck": "“{hook}” was sent to Meta but never confirmed. Otto will not retry it — check the page.",
    "alert.slot_soon": {"one": "“{hook}” is slotted for {when} and still not approved. 1 hour left.",
                        "other": "“{hook}” is slotted for {when} and still not approved. {n} hours left."},
    "alert.missed": "“{hook}” was due {when} and did not publish. Checking the pipeline.",
    # free-trial reminders (otto_trial)
    "trial.your_business": "your business",
    "trial.price": " Plans start at {price} a month.",
    "trial.a_month": "{price} a month",
    "trial.cta": "Choose a plan", "trial.cta_continue": "Choose a plan to continue",
    "trial.day5.subject": "2 days left in your Otto trial",
    "trial.day5.title": "2 days left in your free trial",
    "trial.day5.lead": "Your free trial of Otto ends on {when}. To keep {who} publishing without a break, choose a plan on your billing page.{price} The plan starts when the trial ends, and that is when the first payment is taken. If you don't choose one, nothing is charged and {who} pauses.",
    "trial.day7.subject_today": "Your Otto trial ends today", "trial.day7.subject_tomorrow": "Your Otto trial ends tomorrow",
    "trial.day7.title_today": "Your free trial ends today", "trial.day7.title_tomorrow": "Your free trial ends tomorrow",
    "trial.day7.lead": "Your trial ends at {time} ({day}). Choose a plan now and {who} keeps publishing: the plan starts, and is charged, when the trial ends.{price} If you don't choose one, nothing is charged and publishing and ads pause.",
    "trial.day8.subject": "Your Otto trial has ended",
    "trial.day8.subject_named": "Your Otto trial has ended — {who} is paused",
    "trial.day8.title": "Your free trial has ended",
    "trial.day8.lead_named": "Publishing and ads are paused for {who}. Your work — brand profile, plan, posts and ad previews — is kept for 90 days, until {kept}. Choose a plan to continue where you left off.",
    "trial.day8.lead": "Choose a plan whenever you're ready to start: Otto sets up your first week as soon as you do.",
    "trial.why": "You get this because you started a free Otto trial with {email}.",
    "trial.terms": "Nothing is charged during the trial. A plan you choose starts automatically when the trial ends, and is charged then; without a plan nothing is charged and your account pauses. You choose and change plans on your billing page.",
    "trial.line.posts": "{posts} posts a month, {reels} of them reels",
    "trial.line.paid": "Paid campaigns on {nets}",
    "trial.line.cap": ", ad spend up to {cap} a month",
    "trial.line.matrix": "Monthly ad matrix: {preset}",
    "preset.micro": "4 concepts × 5 styles", "preset.launch": "6 concepts × 6 styles", "preset.scale": "6 concepts × 8 styles",
    # recommendation texts the engine files with an i18n key (recs[].i18n = {"key": …, "args": {…}})
    "rec.connect_meta.title": "Connect Instagram and Facebook for {name}",
    "rec.connect_meta.why": "Otto prepares the first week now, but it can only publish once Meta's own sign-in has linked the Page and the Instagram account. You choose them; nothing posts without your approval.",
    "rec.connect_meta.impact": "Unblocks publishing",
    "rec.pair_telegram.title": "Pair Telegram for {name}",
    "rec.pair_telegram.why": "Approvals, the 07:35 report and alerts arrive in Telegram once your phone is paired. Until then everything waits in the app.",
    "rec.pair_telegram.impact": "Approve from your phone",
    "rec.connect_google.title": "Connect Google Ads for {name}",
    "rec.connect_google.why": "Search ads need your Google Ads account, linked through Google's own sign-in.",
    "rec.connect_google.impact": "Search ads on your budget",
    "rec.compliance_hold.title": "Compliance hold: {subject}",
    "rec.compliance_hold.why": "Otto held this before it reached you: it breaks an advertising rule for your sector or country. Change it in the app before it can go out.",
    "rec.compliance_hold.impact": "Keeps your ad account and brand out of policy trouble",
    "rec.check_live.title": "Check if it went out: {hook}",
    "rec.check_live.why": "Otto sent this post to Meta but never got a confirmation, and will not try again by itself. Check your page: if it is live, mark it published; if not, send it back to review.",
    "rec.check_live.impact": "Prevents a double post",
    "rec.missed.title": "Missed publish: {hook}",
    "rec.missed.why": "This post was approved for {when} but did not go out. Pick a new moment in the app.",
    "rec.missed.impact": "Keeps the calendar honest",
    "rec.linkedin.title": "Post by hand on LinkedIn: {hook}",
    "rec.linkedin.why": "This post is approved for LinkedIn ({when}), where Otto cannot publish yet. Post it yourself; the text is ready in the app.",
    "rec.linkedin.impact": "The post still goes out on time",
    "rec.publish_failed.title": "Publishing failed 3×: {hook}",
    "rec.publish_failed.why": "Meta refused this post three times; it stays unpublished until it is fixed. The details are in the app.",
    "rec.publish_failed.impact": "The post stays unpublished until it is fixed",
    "rec.double_down.title": "Double down on “{pillar}” next week",
    "rec.double_down.why": "Top post: “{hook}” — reach {reach}, saves {saves}. {pillar} carries {k} of the top 5.",
    "rec.double_down.impact": "Next batch iterates on proven angles",
    "rec.pause.title": "Pause “{campaign}” — cost per result above target 3 days running",
    "rec.pause.why": "Target {target} per result; this campaign has been above it three days in a row. Pausing moves the budget to the best performer.",
    "rec.pause.impact": "Stops the bleed the same day",
}

NL = {
    "fmt.reel": "Reel", "fmt.story": "Story", "fmt.carousel": "Carrousel", "fmt.video": "Video",
    "btn.approve": "Goedkeuren", "btn.skip": "Overslaan", "btn.change": "Wijzigen", "btn.not_now": "Niet nu",
    "btn.open_otto": "Open Otto", "btn.approve_plan": "Plan goedkeuren", "btn.review_all": "Alles bekijken in de app",
    "btn.see_in_app": "Bekijk het in de app", "btn.open_in_app_instead": "Liever openen in de app",
    "lbl.image": "Afbeelding", "img.alt": "Afbeelding: {hook}",
    "tz.times": "Alle tijden in lokale tijd ({city}).", "tz.label": " ({city})",
    "prio.P0": "Dringend", "prio.P1": "Aanbevolen",
    "noun.post": {"one": "1 post", "other": "{n} posts"},
    "noun.decision": {"one": "1 beslissing", "other": "{n} beslissingen"},
    "email.why": "Je krijgt deze mail omdat je in Otto de posts van {name} goedkeurt.",
    "email.settings": "Instellingen",
    "email.settings_sentence": "In {settings} kies je hoe goedkeuringen je bereiken.",
    "email.settings_text": "Kies hoe goedkeuringen je bereiken: {url}",
    "email.buttons_once": "Elke knop werkt één keer en verloopt na 72 uur; er gaat niets online zonder jouw akkoord.",
    "email.links_once": "Elke link werkt één keer en verloopt na 72 uur; er gaat niets online zonder jouw akkoord.",
    "digest.subject": {"one": "1 post om goed te keuren voor {name}", "other": "{n} posts om goed te keuren voor {name}"},
    "digest.subject_from": " · vanaf {day}",
    "digest.title": {"one": "1 post wacht op je akkoord", "other": "{n} posts wachten op je akkoord"},
    "digest.lead": "Tik op {approve} en de post gaat op het geplande moment online. Kies je {skip}, dan vult Otto dat moment met iets anders. {change} opent de post in de app.",
    "digest.why": "Waarom deze post: {why}",
    "digest.more": {"one": "Er wacht nog 1 post in de app.", "other": "Er wachten nog {n} posts in de app."},
    "recs.subject_one": "Otto raadt aan: {title}",
    "recs.subject_many": {"one": "1 aanbeveling voor {name}", "other": "{n} aanbevelingen voor {name}"},
    "recs.title_one": "Otto raadt aan",
    "recs.title_many": {"one": "1 beslissing voor je", "other": "{n} beslissingen voor je"},
    "recs.lead": "De voorstellen van je bureau voor deze week. Keur je er een goed, dan gaat Otto ermee aan de slag; met Niet nu leg je het opzij.",
    "recs.impact": "Effect: {impact}",
    "plan.title": "Advertentieplan voor {month} goedkeuren",
    "plan.summary": {"one": "1 campagne, ca. {total}", "other": "{n} campagnes, ca. {total}"},
    "plan.lead": "Er wordt niets uitgegeven tot je akkoord geeft, en elke campagne heeft een vast dagbudget als plafond.",
    "plan.per_day": "{amount} per dag",
    "plan.max_day": "max. {amount} per dag",
    "plan.dates": "{start} t/m {end}",
    "plan.hold": " · wacht op een tekstcontrole",
    "plan.more": "en nog {n} in de app",
    "page.invalid.title": "Deze link werkt niet",
    "page.invalid.text": "Misschien is hij bij het kopiëren afgebroken. Open de mail opnieuw en tik op de knop, of bekijk de post in de app.",
    "page.expired.title": "Deze link is verlopen",
    "page.expired.text": "Knoppen in goedkeuringsmails werken 72 uur. De post wacht nog op je in de app.",
    "page.used.title": "Deze link is al gebruikt",
    "page.used.text": "Elke knop werkt één keer. {result}",
    "page.denied.title": "Deze link kan niet meer worden gebruikt",
    "page.denied.text": "Hij is gestuurd naar iemand die niet meer goedkeurt voor dit merk, of het onderdeel is verplaatst. Open de app om te zien wat er wacht.",
    "page.form.title": "Tik nog een keer op de knop",
    "page.form.text": "Deze pagina stond een tijdje open, dus Otto vraagt het nog een keer. Open de link uit je mail opnieuw.",
    "page.origin.title": "Dat kwam niet van de pagina van Otto",
    "page.origin.text": "Voor je veiligheid neemt Otto alleen beslissingen aan via de eigen bevestigingspagina. Open de link uit je mail opnieuw.",
    "page.rate.title": "Te vaak getikt",
    "page.rate.text": "Wacht een minuutje en probeer het dan opnieuw.",
    "page.config.title": "Otto kan deze link nu niet controleren",
    "page.config.text": "Probeer het over een paar minuten opnieuw, of bekijk de post in de app.",
    "page.nothing.title": "Hier hoef je niets te doen",
    "page.nothing.text": "{why} Je kunt het in de app aanpassen.",
    "page.expires": "Deze knop werkt één keer. De link verloopt op {day} om {time}{tz}.",
    "late.post.approved": "Deze post is al goedgekeurd.",
    "late.post.scheduled": "Deze post staat al ingepland.",
    "late.post.skipped": "Deze post is al overgeslagen.",
    "late.post.published": "Deze post is al gepubliceerd.",
    "late.post.publishing": "Deze post wordt nu gepubliceerd.",
    "late.post.failed": "Deze post wacht al op een nieuw moment.",
    "late.post.other": "Deze post is al {status}.",
    "late.rec.done": "Dit is al afgehandeld.",
    "late.rec.approved": "Dit is al goedgekeurd.",
    "late.rec.dismissed": "Dit is al opzijgelegd.",
    "late.rec.other": "Dit is al {status}.",
    "confirm.post.approve.title": "Deze post goedkeuren?", "confirm.post.approve.btn": "Post goedkeuren",
    "confirm.post.skip.title": "Deze post overslaan?", "confirm.post.skip.btn": "Post overslaan",
    "confirm.rec.approve.title": "Dit goedkeuren?", "confirm.rec.approve.btn": "Goedkeuren",
    "confirm.rec.dismiss.title": "Dit voorlopig opzijleggen?", "confirm.rec.dismiss.btn": "Niet nu",
    "confirm.plan.title": "Advertentieplan voor {month} goedkeuren?", "confirm.plan.btn": "Plan goedkeuren",
    "confirm.post.approve.lead": "De post gaat op het geplande moment online op {platform}.",
    "confirm.page_fallback": "je pagina",
    "confirm.post.skip.lead": "Otto vult dat moment met iets anders.",
    "confirm.plan.lead": "Er wordt niets uitgegeven tot je akkoord geeft; elke campagne houdt haar dagplafond.",
    "confirm.rec.approve.lead": "Otto gaat ermee aan de slag.",
    "confirm.rec.dismiss.lead": "Otto legt het opzij. Je kunt het in de app terughalen.",
    "done.approved.title": "Goedgekeurd",
    "done.post.goes_out": "De post gaat online op {when}.",
    "done.post.passed": "Het geplande moment is voorbij, dus Otto stelt een nieuw moment voor.",
    "done.skipped.title": "Overgeslagen",
    "done.put_away.title": "Voorlopig opzijgelegd",
    "done.put_away.text": "Je kunt het in de app terughalen wanneer je wilt.",
    "done.failed.title": "Goedgekeurd, nog niet gestart",
    "done.failed.text": "Je akkoord is opgeslagen, maar Otto kon er nog niet mee beginnen. Het team van Otto is op de hoogte en rondt het af; intussen wordt er niets uitgegeven.",
    "done.plan.text": {"one": "1 campagne goedgekeurd voor {month}. Ze start op haar eigen datum, met haar dagplafond.",
                       "other": "{n} campagnes goedgekeurd voor {month}. Elke campagne start op haar eigen datum, met haar dagplafond."},
    "done.rec.text": "Klaar: {result}.",
    "done.rec.paused": "de campagne staat op pauze",
    "result.approved_on": "Goedgekeurd op {day} om {time}.",
    "result.skipped_on": "Overgeslagen op {day} om {time}.",
    "result.put_away_on": "Opzijgelegd op {day} om {time}.",
    "report.subject": "Ochtendrapport {day} · {name}",
    "report.subject_waiting": {"one": "1 wacht op je", "other": "{n} wachten op je"},
    "report.subject_clear": "niets te doen",
    "report.title": "Ochtendrapport",
    "report.greeting": "Goedemorgen.",
    "report.sum.paid": "Gisteren: {spend} aan advertenties, {results}.",
    "report.sum.no_results": "nog geen resultaat",
    "report.sum.organic": {"one": "Gisteren ging 1 post online.", "other": "Gisteren gingen {n} posts online."},
    "report.sum.organic_reach": {"one": "Gisteren ging 1 post online en bereikte {reach} mensen.",
                                 "other": "Gisteren gingen {n} posts online en bereikten {reach} mensen."},
    "report.sum.quiet": "Gisteren ging er niets online.",
    "report.sum.starting": "Je eerste posts komen eraan.",
    "report.sum.waiting": {"one": "1 post wacht op je akkoord.", "other": "{n} posts wachten op je akkoord."},
    "report.sum.decisions": {"one": "1 beslissing wacht op je.", "other": "{n} beslissingen wachten op je."},
    "report.sum.both": "{posts} en {decisions} wachten op je.",
    "report.sum.clear": "Vandaag hoef je niets te doen.",
    "report.yesterday": "Gisteren",
    "report.sub.meta": "Meta-advertenties en posts", "report.sub.ads": "Advertenties en posts", "report.sub.posts": "Je posts",
    "report.paid": "Advertenties",
    "report.posts_y": "Posts van gisteren",
    "report.waiting": "Wacht op jou",
    "report.today": "Vandaag",
    "report.today_none": "Voor vandaag staat er niets ingepland.",
    "report.today_done": "al online",
    "report.best_post": "Best gelopen",
    "report.best_ad": "Beste advertentie: ‘{name}’, {cost}.",
    "report.month": "Deze maand tot nu toe: {spent} van {planned} gepland.",
    "report.messages": {"one": "1 persoon begon een chat via je advertenties.", "other": "{n} mensen begonnen een chat via je advertenties."},
    "report.failed": {"one": "1 post is niet online gegaan; de details staan in de app.",
                      "other": "{n} posts zijn niet online gegaan; de details staan in de app."},
    "report.none_yesterday": "Gisteren ging er niets online.",
    "report.first_post": "Je eerste post gaat online op {day} om {time}; de cijfers zie je hier de ochtend erna.",
    "report.cost_line.leads": "Kosten per aanvraag gisteren: {cost}.", "report.cost_line.purchases": "Kosten per verkoop gisteren: {cost}.",
    "report.cost_line.conversions": "Kosten per conversie gisteren: {cost}.", "report.cost_line.results": "Kosten per resultaat gisteren: {cost}.",
    "report.first_pending": "Je eerste post staat klaar voor {day} om {time}: keur hem hieronder goed, dan zie je de cijfers hier de ochtend erna.",
    "report.today_waiting": "wacht op je akkoord",
    "report.first_none": "Je eerste posts worden voorbereid; de cijfers zie je hier de ochtend nadat ze online zijn gegaan.",
    "report.drop": "Let op: {metric} gedaald naar {value} (7-daags gemiddelde {avg}).",
    "report.paid.trial": "Je advertenties staan klaar om te bekijken. Ze starten zodra je een plan kiest; tijdens je proefperiode wordt er niets uitgegeven.",
    "report.paid.not_connected": "Koppel je Meta-advertentieaccount in Otto, dan zie je hier wat je advertenties kosten en opleveren.",
    "report.paid.pending": "De advertentiecijfers van gisteren zijn er nog niet; je ziet ze morgen in je rapport.",
    "report.paid.idle": "Gisteren liepen er geen advertentiecampagnes.",
    "report.paid.next": "De volgende campagne start op {day}.",
    "report.why": "Je krijgt dit rapport elke ochtend om 07:35 omdat je in Otto de posts van {name} goedkeurt.",
    "report.settings_sentence": "In {settings} kies je hoe rapporten en goedkeuringen je bereiken.",
    "report.settings_text": "Kies hoe rapporten en goedkeuringen je bereiken: {url}",
    "kpi.spent": "Uitgegeven", "kpi.leads": "Aanvragen", "kpi.purchases": "Verkopen", "kpi.conversions": "Conversies",
    "kpi.results": "Resultaat", "kpi.reach": "Bereik", "kpi.clicks": "Klikken", "kpi.reactions": "Reacties",
    "kpi.within_budget": "binnen je dagbudget van {budget}",
    "kpi.over_budget": "dagbudget {budget}; Meta middelt dit uit over de week",
    "kpi.avg7": "7-daags gemiddelde {avg}",
    "kpi.of_posts": {"one": "van 1 post", "other": "van {n} posts"},
    "chart.per_day": "{label} per dag", "chart.spend": "Uitgaven per dag",
    "res.leads": {"one": "1 aanvraag", "other": "{n} aanvragen"},
    "res.purchases": {"one": "1 verkoop", "other": "{n} verkopen"},
    "res.conversions": {"one": "1 conversie", "other": "{n} conversies"},
    "res.engagements": {"one": "1 interactie", "other": "{n} interacties"},
    "res.landing": {"one": "1 paginaweergave", "other": "{n} paginaweergaven"},
    "cost.leads": "{cost} per aanvraag", "cost.purchases": "{cost} per verkoop", "cost.conversions": "{cost} per conversie",
    "cost.results": "{cost} per resultaat",
    "m.reach": "{n} bereikt",
    "m.clicks": {"one": "1 klik", "other": "{n} klikken"},
    "m.reactions": {"one": "1 reactie", "other": "{n} reacties"},
    "m.saves": {"one": "1 keer bewaard", "other": "{n} keer bewaard"},
    "m.pending": "De cijfers volgen morgen in je rapport.",
    "metric.reach": "bereik", "metric.clicks": "klikken", "metric.saves": "bewaard", "metric.followers": "volgers",
    "metric.leads": "aanvragen", "metric.page_reach_week": "weekbereik van je pagina",
    "tg.approve": "✅ Goedkeuren", "tg.skip": "❌ Overslaan", "tg.edit": "✏️ Wijzigen", "tg.later": "↷ Later", "tg.not_now": "Niet nu",
    "tg.rec_head": "💡 Je bureau raadt aan · {prio}",
    "tg.not_yours": "Dit is niet jouw Otto.",
    "tg.unknown_post": "Onbekende post", "tg.unknown_rec": "Onbekende aanbeveling",
    "tg.already": "Al {state}",
    "status.approved": "goedgekeurd", "status.scheduled": "ingepland", "status.skipped": "overgeslagen",
    "status.published": "gepubliceerd", "status.publishing": "bezig met publiceren", "status.failed": "mislukt",
    "status.draft": "in concept", "status.pending_approval": "in afwachting", "status.proposed": "voorgesteld",
    "status.dismissed": "opzijgelegd", "status.done": "afgehandeld",
    "tg.note.approve": "✅ Goedgekeurd · online op {when}",
    "tg.note.skip": "❌ Overgeslagen — Otto vult het moment opnieuw",
    "tg.note.later": "↷ Later — je krijgt hem morgenochtend opnieuw",
    "tg.rec.on_it": "✅ Goedgekeurd — Otto gaat ermee aan de slag",
    "tg.rec.failed": "✅ Goedgekeurd, nog niet gestart — het team pakt het op",
    "tg.rec.approved": "✅ Goedgekeurd",
    "tg.rec.dismissed": "Opzijgelegd",
    "tg.rec.tail_done": "✅ Goedgekeurd — {result}",
    "tg.rec.tail_failed": "✅ Goedgekeurd — nog niet gestart: het is mislukt, het team is op de hoogte",
    "tg.rec.tail_dismissed": "— Niet nu",
    "tg.edit.answer": "Antwoord met de wijziging die je wilt",
    "tg.edit.prompt": "✏️ {pid} — antwoord op DIT bericht met wat er anders moet (bijv. ‘korter, noem de labtests’). Quill herschrijft de post en stuurt een nieuwe kaart. (2 uur geldig.)",
    "tg.edit.expired": "De wijzigingsvraag voor {pid} is verlopen (2 uur). Tik nog een keer op ✏️ Wijzigen op de kaart.",
    "tg.edit.got_it": "Begrepen — Quill herschrijft {pid}: ‘{note}’. Je krijgt zo een nieuwe kaart.",
    "tg.edit.too_late": "{pid} is al {state}, de wijziging is niet doorgevoerd.",
    "tg.cards": {"one": "1 post: tik op ✅ Goedkeuren op de kaart", "other": "{n} posts: tik op ✅ Goedkeuren op de kaarten"},
    "tg.open": "Open Otto: {url}",
    "alert.head": "Melding van Otto",
    "alert.drop": "Daling bij {brand}: {metric} staat op {value}, {pct}% of meer onder het 7-daags gemiddelde ({avg}). Even naar kijken.",
    "alert.stuck": "‘{hook}’ is naar Meta gestuurd maar nooit bevestigd. Otto probeert het niet opnieuw; kijk even op je pagina.",
    "alert.slot_soon": {"one": "‘{hook}’ staat gepland voor {when} en is nog niet goedgekeurd. Nog 1 uur.",
                        "other": "‘{hook}’ staat gepland voor {when} en is nog niet goedgekeurd. Nog {n} uur."},
    "alert.missed": "‘{hook}’ stond gepland voor {when} en is niet gepubliceerd. We zoeken uit wat er misging.",
    "trial.your_business": "je bedrijf",
    "trial.price": " Plannen beginnen bij {price} per maand.",
    "trial.a_month": "{price} per maand",
    "trial.cta": "Kies een plan", "trial.cta_continue": "Kies een plan en ga verder",
    "trial.day5.subject": "Nog 2 dagen in je proefperiode van Otto",
    "trial.day5.title": "Nog 2 dagen in je gratis proefperiode",
    "trial.day5.lead": "Je gratis proefperiode van Otto eindigt op {when}. Wil je dat {who} zonder onderbreking blijft posten? Kies dan een plan op je betaalpagina.{price} Het plan gaat in zodra de proefperiode afloopt, en dan wordt ook de eerste betaling afgeschreven. Kies je geen plan, dan wordt er niets afgeschreven en gaat {who} op pauze.",
    "trial.day7.subject_today": "Je proefperiode van Otto eindigt vandaag",
    "trial.day7.subject_tomorrow": "Je proefperiode van Otto eindigt morgen",
    "trial.day7.title_today": "Je gratis proefperiode eindigt vandaag",
    "trial.day7.title_tomorrow": "Je gratis proefperiode eindigt morgen",
    "trial.day7.lead": "Je proefperiode eindigt om {time} ({day}). Kies nu een plan, dan blijft {who} gewoon posten: het plan gaat in zodra de proefperiode afloopt en wordt dan afgeschreven.{price} Kies je geen plan, dan wordt er niets afgeschreven en stoppen de posts en advertenties.",
    "trial.day8.subject": "Je proefperiode van Otto is afgelopen",
    "trial.day8.subject_named": "Je proefperiode van Otto is afgelopen: {who} staat op pauze",
    "trial.day8.title": "Je gratis proefperiode is afgelopen",
    "trial.day8.lead_named": "De posts en advertenties van {who} staan op pauze. Je werk (merkprofiel, planning, posts en advertentievoorbeelden) bewaren we 90 dagen, tot {kept}. Kies een plan en ga verder waar je gebleven was.",
    "trial.day8.lead": "Kies een plan zodra je wilt beginnen: Otto zet dan meteen je eerste week klaar.",
    "trial.why": "Je krijgt deze mail omdat je met {email} een gratis proefperiode van Otto bent gestart.",
    "trial.terms": "Tijdens de proefperiode wordt er niets afgeschreven. Een plan dat je kiest, gaat automatisch in zodra de proefperiode afloopt en wordt dan afgeschreven; zonder plan wordt er niets afgeschreven en gaat je account op pauze. Een plan kiezen of wijzigen doe je op je betaalpagina.",
    "trial.line.posts": "{posts} posts per maand, waarvan {reels} reels",
    "trial.line.paid": "Advertentiecampagnes op {nets}",
    "trial.line.cap": ", advertentiebudget tot {cap} per maand",
    "trial.line.matrix": "Maandelijkse advertentiematrix: {preset}",
    "preset.micro": "4 concepten × 5 stijlen", "preset.launch": "6 concepten × 6 stijlen", "preset.scale": "6 concepten × 8 stijlen",
    "rec.connect_meta.title": "Koppel Instagram en Facebook voor {name}",
    "rec.connect_meta.why": "Otto bereidt de eerste week nu al voor, maar kan pas publiceren als je via Meta zelf je pagina en Instagram-account hebt gekoppeld. Jij kiest welke; er gaat niets online zonder jouw akkoord.",
    "rec.connect_meta.impact": "Dan kan Otto publiceren",
    "rec.pair_telegram.title": "Koppel Telegram voor {name}",
    "rec.pair_telegram.why": "Goedkeuringen, het rapport van 07:35 en meldingen komen in Telegram binnen zodra je telefoon gekoppeld is. Tot die tijd wacht alles in de app.",
    "rec.pair_telegram.impact": "Goedkeuren vanaf je telefoon",
    "rec.connect_google.title": "Koppel Google Ads voor {name}",
    "rec.connect_google.why": "Zoekadvertenties hebben je Google Ads-account nodig, gekoppeld via de eigen inlog van Google.",
    "rec.connect_google.impact": "Zoekadvertenties binnen je budget",
    "rec.compliance_hold.title": "Tegengehouden vanwege de regels: {subject}",
    "rec.compliance_hold.why": "Otto heeft dit tegengehouden voordat het bij je kwam: het overtreedt een reclameregel voor jouw branche of land. Pas het aan in de app voordat het online kan.",
    "rec.compliance_hold.impact": "Houdt je advertentieaccount en je merk uit de problemen",
    "rec.check_live.title": "Kijk even of dit online staat: {hook}",
    "rec.check_live.why": "Otto heeft deze post naar Meta gestuurd maar nooit een bevestiging gekregen, en probeert het niet zelf opnieuw. Kijk op je pagina: staat hij online, markeer hem dan als gepubliceerd; zo niet, stuur hem terug om te beoordelen.",
    "rec.check_live.impact": "Voorkomt een dubbele post",
    "rec.missed.title": "Niet gepubliceerd: {hook}",
    "rec.missed.why": "Deze post was goedgekeurd voor {when} maar is niet online gegaan. Kies in de app een nieuw moment.",
    "rec.missed.impact": "Houdt je planning kloppend",
    "rec.linkedin.title": "Zelf posten op LinkedIn: {hook}",
    "rec.linkedin.why": "Deze post is goedgekeurd voor LinkedIn ({when}), waar Otto nog niet kan publiceren. Post hem zelf; de tekst staat klaar in de app.",
    "rec.linkedin.impact": "De post gaat alsnog op tijd online",
    "rec.publish_failed.title": "Publiceren 3× mislukt: {hook}",
    "rec.publish_failed.why": "Meta heeft deze post drie keer geweigerd; hij blijft offline tot het is opgelost. De details staan in de app.",
    "rec.publish_failed.impact": "De post blijft offline tot het is opgelost",
    "rec.double_down.title": "Volgende week meer ‘{pillar}’",
    "rec.double_down.why": "Beste post: ‘{hook}’, bereik {reach}, {saves} keer bewaard. {pillar} levert {k} van de beste 5.",
    "rec.double_down.impact": "De volgende reeks bouwt voort op wat werkt",
    "rec.pause.title": "Pauzeer ‘{campaign}’: drie dagen boven de doelprijs per resultaat",
    "rec.pause.why": "Het doel is {target} per resultaat; deze campagne zit daar drie dagen op rij boven. Pauzeren verschuift het budget naar de best lopende campagne.",
    "rec.pause.impact": "Stopt het weglekken nog dezelfde dag",
}

DE = {
    "fmt.reel": "Reel", "fmt.story": "Story", "fmt.carousel": "Karussell", "fmt.video": "Video",
    "btn.approve": "Freigeben", "btn.skip": "Überspringen", "btn.change": "Ändern", "btn.not_now": "Nicht jetzt",
    "btn.open_otto": "Otto öffnen", "btn.approve_plan": "Plan freigeben", "btn.review_all": "Alle in der App ansehen",
    "btn.see_in_app": "In der App ansehen", "btn.open_in_app_instead": "Stattdessen in der App öffnen",
    "lbl.image": "Bild", "img.alt": "Bild: {hook}",
    "tz.times": "Alle Uhrzeiten in Ortszeit ({city}).", "tz.label": " ({city})",
    "prio.P0": "Dringend", "prio.P1": "Empfohlen",
    "noun.post": {"one": "1 Beitrag", "other": "{n} Beiträge"},
    "noun.decision": {"one": "1 Entscheidung", "other": "{n} Entscheidungen"},
    "email.why": {"Sie": "Sie erhalten diese E-Mail, weil Sie in Otto die Beiträge von {name} freigeben.",
                  "du": "Du erhältst diese E-Mail, weil du in Otto die Beiträge von {name} freigibst."},
    "email.settings": "Einstellungen",
    "email.settings_sentence": {"Sie": "In den {settings} legen Sie fest, wie Freigaben Sie erreichen.",
                                "du": "In den {settings} legst du fest, wie Freigaben dich erreichen."},
    "email.settings_text": {"Sie": "Legen Sie fest, wie Freigaben Sie erreichen: {url}",
                            "du": "Leg fest, wie Freigaben dich erreichen: {url}"},
    "email.buttons_once": {"Sie": "Jeder Button funktioniert einmal und läuft nach 72 Stunden ab; ohne Ihre Freigabe wird nichts veröffentlicht.",
                           "du": "Jeder Button funktioniert einmal und läuft nach 72 Stunden ab; ohne deine Freigabe wird nichts veröffentlicht."},
    "email.links_once": {"Sie": "Jeder Link funktioniert einmal und läuft nach 72 Stunden ab; ohne Ihre Freigabe wird nichts veröffentlicht.",
                         "du": "Jeder Link funktioniert einmal und läuft nach 72 Stunden ab; ohne deine Freigabe wird nichts veröffentlicht."},
    "digest.subject": {"one": "1 Beitrag zur Freigabe für {name}", "other": "{n} Beiträge zur Freigabe für {name}"},
    "digest.subject_from": " · ab {day}",
    "digest.title": {"Sie": {"one": "1 Beitrag wartet auf Ihre Freigabe", "other": "{n} Beiträge warten auf Ihre Freigabe"},
                     "du": {"one": "1 Beitrag wartet auf deine Freigabe", "other": "{n} Beiträge warten auf deine Freigabe"}},
    "digest.lead": {"Sie": "Tippen Sie auf {approve}, und der Beitrag geht zur geplanten Zeit online. Bei {skip} füllt Otto den Termin mit etwas anderem. {change} öffnet den Beitrag in der App.",
                    "du": "Tippe auf {approve}, und der Beitrag geht zur geplanten Zeit online. Bei {skip} füllt Otto den Termin mit etwas anderem. {change} öffnet den Beitrag in der App."},
    "digest.why": "Warum dieser Beitrag: {why}",
    "digest.more": {"one": "In der App wartet noch 1 weiterer Beitrag.", "other": "In der App warten noch {n} weitere Beiträge."},
    "recs.subject_one": "Otto empfiehlt: {title}",
    "recs.subject_many": {"one": "1 Empfehlung für {name}", "other": "{n} Empfehlungen für {name}"},
    "recs.title_one": "Otto empfiehlt",
    "recs.title_many": {"Sie": {"one": "1 Entscheidung für Sie", "other": "{n} Entscheidungen für Sie"},
                        "du": {"one": "1 Entscheidung für dich", "other": "{n} Entscheidungen für dich"}},
    "recs.lead": {"Sie": "Die Vorschläge Ihrer Agentur für diese Woche. Geben Sie einen frei, kümmert sich Otto darum; mit „Nicht jetzt“ legen Sie ihn beiseite.",
                  "du": "Die Vorschläge deiner Agentur für diese Woche. Gibst du einen frei, kümmert sich Otto darum; mit „Nicht jetzt“ legst du ihn beiseite."},
    "recs.impact": "Wirkung: {impact}",
    "plan.title": "Anzeigenplan für {month} freigeben",
    "plan.summary": {"one": "1 Kampagne, ca. {total}", "other": "{n} Kampagnen, ca. {total}"},
    "plan.lead": {"Sie": "Es wird nichts ausgegeben, bevor Sie freigeben, und jede Kampagne hat ein festes Tageslimit.",
                  "du": "Es wird nichts ausgegeben, bevor du freigibst, und jede Kampagne hat ein festes Tageslimit."},
    "plan.per_day": "{amount}/Tag",
    "plan.max_day": "max. {amount} pro Tag",
    "plan.dates": "{start} bis {end}",
    "plan.hold": " · wartet auf eine Textprüfung",
    "plan.more": "und {n} weitere in der App",
    "page.invalid.title": "Dieser Link funktioniert nicht",
    "page.invalid.text": {"Sie": "Vielleicht wurde er beim Kopieren abgeschnitten. Öffnen Sie die E-Mail noch einmal und tippen Sie auf den Button, oder sehen Sie sich den Beitrag in der App an.",
                          "du": "Vielleicht wurde er beim Kopieren abgeschnitten. Öffne die E-Mail noch einmal und tippe auf den Button, oder sieh dir den Beitrag in der App an."},
    "page.expired.title": "Dieser Link ist abgelaufen",
    "page.expired.text": {"Sie": "Buttons in Freigabe-E-Mails funktionieren 72 Stunden lang. Der Beitrag wartet in der App weiter auf Sie.",
                          "du": "Buttons in Freigabe-E-Mails funktionieren 72 Stunden lang. Der Beitrag wartet in der App weiter auf dich."},
    "page.used.title": "Dieser Link wurde bereits verwendet",
    "page.used.text": "Jeder Button funktioniert nur einmal. {result}",
    "page.denied.title": "Dieser Link kann nicht mehr verwendet werden",
    "page.denied.text": {"Sie": "Er wurde an jemanden geschickt, der für diese Marke nicht mehr freigibt, oder der Eintrag wurde verschoben. Öffnen Sie die App, um zu sehen, was wartet.",
                         "du": "Er wurde an jemanden geschickt, der für diese Marke nicht mehr freigibt, oder der Eintrag wurde verschoben. Öffne die App, um zu sehen, was wartet."},
    "page.form.title": {"Sie": "Bitte tippen Sie noch einmal auf den Button", "du": "Bitte tippe noch einmal auf den Button"},
    "page.form.text": {"Sie": "Diese Seite war eine Weile geöffnet, deshalb fragt Otto noch einmal nach. Öffnen Sie den Link aus Ihrer E-Mail erneut.",
                       "du": "Diese Seite war eine Weile geöffnet, deshalb fragt Otto noch einmal nach. Öffne den Link aus deiner E-Mail erneut."},
    "page.origin.title": "Das kam nicht von Ottos Seite",
    "page.origin.text": {"Sie": "Zu Ihrer Sicherheit nimmt Otto Entscheidungen nur über die eigene Bestätigungsseite an. Öffnen Sie den Link aus Ihrer E-Mail erneut.",
                         "du": "Zu deiner Sicherheit nimmt Otto Entscheidungen nur über die eigene Bestätigungsseite an. Öffne den Link aus deiner E-Mail erneut."},
    "page.rate.title": "Zu viele Versuche",
    "page.rate.text": {"Sie": "Bitte warten Sie eine Minute und versuchen Sie es dann erneut.",
                       "du": "Bitte warte eine Minute und versuch es dann noch einmal."},
    "page.config.title": "Otto kann diesen Link gerade nicht prüfen",
    "page.config.text": {"Sie": "Bitte versuchen Sie es in ein paar Minuten noch einmal, oder sehen Sie sich den Beitrag in der App an.",
                         "du": "Bitte versuch es in ein paar Minuten noch einmal, oder sieh dir den Beitrag in der App an."},
    "page.nothing.title": "Hier ist nichts zu tun",
    "page.nothing.text": {"Sie": "{why} Sie können das in der App ändern.", "du": "{why} Du kannst das in der App ändern."},
    "page.expires": "Dieser Button funktioniert einmal. Der Link läuft am {day} um {time} Uhr ab{tz}.",
    "late.post.approved": "Dieser Beitrag ist bereits freigegeben.",
    "late.post.scheduled": "Dieser Beitrag ist bereits eingeplant.",
    "late.post.skipped": "Dieser Beitrag wurde bereits übersprungen.",
    "late.post.published": "Dieser Beitrag ist bereits veröffentlicht.",
    "late.post.publishing": "Dieser Beitrag wird gerade veröffentlicht.",
    "late.post.failed": "Dieser Beitrag wartet bereits auf einen neuen Termin.",
    "late.post.other": "Dieser Beitrag ist bereits {status}.",
    "late.rec.done": "Das wurde bereits erledigt.",
    "late.rec.approved": "Das wurde bereits freigegeben.",
    "late.rec.dismissed": "Das wurde bereits zurückgestellt.",
    "late.rec.other": "Das ist bereits {status}.",
    "confirm.post.approve.title": "Diesen Beitrag freigeben?", "confirm.post.approve.btn": "Beitrag freigeben",
    "confirm.post.skip.title": "Diesen Beitrag überspringen?", "confirm.post.skip.btn": "Beitrag überspringen",
    "confirm.rec.approve.title": "Das freigeben?", "confirm.rec.approve.btn": "Freigeben",
    "confirm.rec.dismiss.title": "Das vorerst zurückstellen?", "confirm.rec.dismiss.btn": "Nicht jetzt",
    "confirm.plan.title": "Anzeigenplan für {month} freigeben?", "confirm.plan.btn": "Plan freigeben",
    "confirm.post.approve.lead": "Der Beitrag geht zur geplanten Zeit auf {platform} online.",
    "confirm.page_fallback": {"Sie": "Ihrer Seite", "du": "deiner Seite"},
    "confirm.post.skip.lead": "Otto füllt den Termin mit etwas anderem.",
    "confirm.plan.lead": {"Sie": "Es wird nichts ausgegeben, bevor Sie freigeben; jede Kampagne behält ihr Tageslimit.",
                          "du": "Es wird nichts ausgegeben, bevor du freigibst; jede Kampagne behält ihr Tageslimit."},
    "confirm.rec.approve.lead": "Otto kümmert sich darum.",
    "confirm.rec.dismiss.lead": {"Sie": "Otto legt es beiseite. Sie können es in der App zurückholen.",
                                 "du": "Otto legt es beiseite. Du kannst es in der App zurückholen."},
    "done.approved.title": "Freigegeben",
    "done.post.goes_out": "Der Beitrag geht am {when} online.",
    "done.post.passed": {"Sie": "Der geplante Termin ist vorbei, deshalb schlägt Otto Ihnen einen neuen vor.",
                         "du": "Der geplante Termin ist vorbei, deshalb schlägt Otto dir einen neuen vor."},
    "done.skipped.title": "Übersprungen",
    "done.put_away.title": "Vorerst zurückgestellt",
    "done.put_away.text": {"Sie": "Sie können es jederzeit in der App zurückholen.", "du": "Du kannst es jederzeit in der App zurückholen."},
    "done.failed.title": "Freigegeben, noch nicht gestartet",
    "done.failed.text": {"Sie": "Ihre Freigabe ist gespeichert, aber Otto konnte gerade nicht damit beginnen. Das Otto-Team ist informiert und erledigt es; bis dahin wird nichts ausgegeben.",
                         "du": "Deine Freigabe ist gespeichert, aber Otto konnte gerade nicht damit beginnen. Das Otto-Team ist informiert und erledigt es; bis dahin wird nichts ausgegeben."},
    "done.plan.text": {"one": "1 Kampagne für {month} freigegeben. Sie startet an ihrem Datum mit ihrem Tageslimit.",
                       "other": "{n} Kampagnen für {month} freigegeben. Jede startet an ihrem Datum mit ihrem Tageslimit."},
    "done.rec.text": "Erledigt: {result}.",
    "done.rec.paused": "die Kampagne ist pausiert",
    "result.approved_on": "Freigegeben am {day} um {time} Uhr.",
    "result.skipped_on": "Übersprungen am {day} um {time} Uhr.",
    "result.put_away_on": "Zurückgestellt am {day} um {time} Uhr.",
    "report.subject": "Morgenbericht {day} · {name}",
    "report.subject_waiting": {"one": "1 zur Freigabe", "other": "{n} zur Freigabe"},
    "report.subject_clear": "nichts zu tun",
    "report.title": "Morgenbericht",
    "report.greeting": "Guten Morgen.",
    "report.sum.paid": "Gestern: {spend} für Anzeigen, {results}.",
    "report.sum.no_results": "noch keine Ergebnisse",
    "report.sum.organic": {"one": "Gestern ging 1 Beitrag online.", "other": "Gestern gingen {n} Beiträge online."},
    "report.sum.organic_reach": {"one": "Gestern ging 1 Beitrag online und erreichte {reach} Menschen.",
                                 "other": "Gestern gingen {n} Beiträge online und erreichten {reach} Menschen."},
    "report.sum.quiet": "Gestern ging nichts online.",
    "report.sum.starting": {"Sie": "Ihre ersten Beiträge sind unterwegs.", "du": "Deine ersten Beiträge sind unterwegs."},
    "report.sum.waiting": {"Sie": {"one": "1 Beitrag wartet auf Ihre Freigabe.", "other": "{n} Beiträge warten auf Ihre Freigabe."},
                           "du": {"one": "1 Beitrag wartet auf deine Freigabe.", "other": "{n} Beiträge warten auf deine Freigabe."}},
    "report.sum.decisions": {"Sie": {"one": "1 Entscheidung wartet auf Sie.", "other": "{n} Entscheidungen warten auf Sie."},
                             "du": {"one": "1 Entscheidung wartet auf dich.", "other": "{n} Entscheidungen warten auf dich."}},
    "report.sum.both": {"Sie": "{posts} und {decisions} warten auf Sie.", "du": "{posts} und {decisions} warten auf dich."},
    "report.sum.clear": {"Sie": "Heute ist nichts für Sie zu tun.", "du": "Heute gibt es für dich nichts zu tun."},
    "report.yesterday": "Gestern",
    "report.sub.meta": "Meta-Anzeigen und Beiträge", "report.sub.ads": "Anzeigen und Beiträge",
    "report.sub.posts": {"Sie": "Ihre Beiträge", "du": "Deine Beiträge"},
    "report.paid": "Anzeigen",
    "report.posts_y": "Beiträge von gestern",
    "report.waiting": {"Sie": "Wartet auf Sie", "du": "Wartet auf dich"},
    "report.today": "Heute",
    "report.today_none": "Für heute ist nichts geplant.",
    "report.today_done": "bereits online",
    "report.best_post": "Bester Beitrag",
    "report.best_ad": "Beste Anzeige: „{name}“, {cost}.",
    "report.month": "Diesen Monat bisher: {spent} von {planned} geplant.",
    "report.messages": {"Sie": {"one": "1 Person hat über Ihre Anzeigen einen Chat begonnen.",
                                "other": "{n} Personen haben über Ihre Anzeigen einen Chat begonnen."},
                        "du": {"one": "1 Person hat über deine Anzeigen einen Chat begonnen.",
                               "other": "{n} Personen haben über deine Anzeigen einen Chat begonnen."}},
    "report.failed": {"one": "1 Beitrag ist nicht online gegangen; die Details stehen in der App.",
                      "other": "{n} Beiträge sind nicht online gegangen; die Details stehen in der App."},
    "report.none_yesterday": "Gestern ging nichts online.",
    "report.first_post": {"Sie": "Ihr erster Beitrag geht am {day} um {time} Uhr online; die Zahlen sehen Sie hier am Morgen danach.",
                          "du": "Dein erster Beitrag geht am {day} um {time} Uhr online; die Zahlen siehst du hier am Morgen danach."},
    "report.cost_line.leads": "Kosten pro Anfrage gestern: {cost}.", "report.cost_line.purchases": "Kosten pro Verkauf gestern: {cost}.",
    "report.cost_line.conversions": "Kosten pro Conversion gestern: {cost}.", "report.cost_line.results": "Kosten pro Ergebnis gestern: {cost}.",
    "report.first_pending": {"Sie": "Ihr erster Beitrag ist für {day} um {time} Uhr bereit: Geben Sie ihn unten frei, dann sehen Sie die Zahlen hier am Morgen danach.",
                             "du": "Dein erster Beitrag ist für {day} um {time} Uhr bereit: Gib ihn unten frei, dann siehst du die Zahlen hier am Morgen danach."},
    "report.today_waiting": {"Sie": "wartet auf Ihre Freigabe", "du": "wartet auf deine Freigabe"},
    "report.first_none": {"Sie": "Ihre ersten Beiträge werden vorbereitet; die Zahlen sehen Sie hier am Morgen nach der Veröffentlichung.",
                          "du": "Deine ersten Beiträge werden vorbereitet; die Zahlen siehst du hier am Morgen nach der Veröffentlichung."},
    "report.drop": "Achtung: {metric} auf {value} gefallen (7-Tage-Schnitt {avg}).",
    "report.paid.trial": {"Sie": "Ihre Anzeigen sind zur Vorschau geplant und starten, sobald Sie einen Tarif wählen; während der Testphase wird nichts ausgegeben.",
                          "du": "Deine Anzeigen sind zur Vorschau geplant und starten, sobald du einen Tarif wählst; während der Testphase wird nichts ausgegeben."},
    "report.paid.not_connected": {"Sie": "Verbinden Sie Ihr Meta-Werbekonto in Otto, dann sehen Sie hier, was Ihre Anzeigen kosten und bringen.",
                                  "du": "Verbinde dein Meta-Werbekonto in Otto, dann siehst du hier, was deine Anzeigen kosten und bringen."},
    "report.paid.pending": {"Sie": "Die Anzeigenzahlen von gestern liegen noch nicht vor; Sie sehen sie morgen im Bericht.",
                            "du": "Die Anzeigenzahlen von gestern liegen noch nicht vor; du siehst sie morgen im Bericht."},
    "report.paid.idle": "Gestern liefen keine Anzeigenkampagnen.",
    "report.paid.next": "Die nächste Kampagne startet am {day}.",
    "report.why": {"Sie": "Sie erhalten diesen Bericht jeden Morgen um 07:35 Uhr, weil Sie in Otto die Beiträge von {name} freigeben.",
                   "du": "Du erhältst diesen Bericht jeden Morgen um 07:35 Uhr, weil du in Otto die Beiträge von {name} freigibst."},
    "report.settings_sentence": {"Sie": "In den {settings} legen Sie fest, wie Berichte und Freigaben Sie erreichen.",
                                 "du": "In den {settings} legst du fest, wie Berichte und Freigaben dich erreichen."},
    "report.settings_text": {"Sie": "Legen Sie fest, wie Berichte und Freigaben Sie erreichen: {url}",
                             "du": "Leg fest, wie Berichte und Freigaben dich erreichen: {url}"},
    "kpi.spent": "Ausgegeben", "kpi.leads": "Anfragen", "kpi.purchases": "Verkäufe", "kpi.conversions": "Conversions",
    "kpi.results": "Ergebnisse", "kpi.reach": "Reichweite", "kpi.clicks": "Klicks", "kpi.reactions": "Reaktionen",
    "kpi.within_budget": {"Sie": "innerhalb Ihres Tagesbudgets von {budget}", "du": "innerhalb deines Tagesbudgets von {budget}"},
    "kpi.over_budget": "Tagesbudget {budget}; Meta gleicht das über die Woche aus",
    "kpi.avg7": "7-Tage-Schnitt {avg}",
    "kpi.of_posts": {"one": "aus 1 Beitrag", "other": "aus {n} Beiträgen"},
    "chart.per_day": "{label} pro Tag", "chart.spend": "Ausgaben pro Tag",
    "res.leads": {"one": "1 Anfrage", "other": "{n} Anfragen"},
    "res.purchases": {"one": "1 Verkauf", "other": "{n} Verkäufe"},
    "res.conversions": {"one": "1 Conversion", "other": "{n} Conversions"},
    "res.engagements": {"one": "1 Interaktion", "other": "{n} Interaktionen"},
    "res.landing": {"one": "1 Seitenaufruf", "other": "{n} Seitenaufrufe"},
    "cost.leads": "{cost} pro Anfrage", "cost.purchases": "{cost} pro Verkauf", "cost.conversions": "{cost} pro Conversion",
    "cost.results": "{cost} pro Ergebnis",
    "m.reach": "{n} erreicht",
    "m.clicks": {"one": "1 Klick", "other": "{n} Klicks"},
    "m.reactions": {"one": "1 Reaktion", "other": "{n} Reaktionen"},
    "m.saves": {"one": "1-mal gespeichert", "other": "{n}-mal gespeichert"},
    "m.pending": {"Sie": "Die Zahlen folgen morgen in Ihrem Bericht.", "du": "Die Zahlen folgen morgen in deinem Bericht."},
    "metric.reach": "Reichweite", "metric.clicks": "Klicks", "metric.saves": "Speicherungen", "metric.followers": "Follower",
    "metric.leads": "Anfragen", "metric.page_reach_week": "Wochenreichweite der Seite",
    "tg.approve": "✅ Freigeben", "tg.skip": "❌ Überspringen", "tg.edit": "✏️ Ändern", "tg.later": "↷ Später",
    "tg.not_now": "Nicht jetzt",
    "tg.rec_head": {"Sie": "💡 Ihre Agentur empfiehlt · {prio}", "du": "💡 Deine Agentur empfiehlt · {prio}"},
    "tg.not_yours": {"Sie": "Das ist nicht Ihr Otto.", "du": "Das ist nicht dein Otto."},
    "tg.unknown_post": "Unbekannter Beitrag", "tg.unknown_rec": "Unbekannte Empfehlung",
    "tg.already": "Bereits {state}",
    "status.approved": "freigegeben", "status.scheduled": "eingeplant", "status.skipped": "übersprungen",
    "status.published": "veröffentlicht", "status.publishing": "in Veröffentlichung", "status.failed": "fehlgeschlagen",
    "status.draft": "im Entwurf", "status.pending_approval": "in Prüfung", "status.proposed": "vorgeschlagen",
    "status.dismissed": "zurückgestellt", "status.done": "erledigt",
    "tg.note.approve": "✅ Freigegeben · erscheint am {when}",
    "tg.note.skip": "❌ Übersprungen — Otto füllt den Termin neu",
    "tg.note.later": {"Sie": "↷ Später — Sie bekommen ihn morgen früh wieder", "du": "↷ Später — du bekommst ihn morgen früh wieder"},
    "tg.rec.on_it": "✅ Freigegeben — Otto kümmert sich darum",
    "tg.rec.failed": "✅ Freigegeben, noch nicht gestartet — das Team kümmert sich darum",
    "tg.rec.approved": "✅ Freigegeben",
    "tg.rec.dismissed": "Zurückgestellt",
    "tg.rec.tail_done": "✅ Freigegeben — {result}",
    "tg.rec.tail_failed": "✅ Freigegeben — noch nicht gestartet: Es ist fehlgeschlagen, das Team ist informiert",
    "tg.rec.tail_dismissed": "— Nicht jetzt",
    "tg.edit.answer": {"Sie": "Antworten Sie mit der gewünschten Änderung", "du": "Antworte mit der gewünschten Änderung"},
    "tg.edit.prompt": {"Sie": "✏️ {pid} — antworten Sie auf DIESE Nachricht mit der gewünschten Änderung (z. B. „kürzer, die Labortests erwähnen“). Quill schreibt den Beitrag um und schickt eine neue Karte. (2 Stunden gültig.)",
                       "du": "✏️ {pid} — antworte auf DIESE Nachricht mit der gewünschten Änderung (z. B. „kürzer, die Labortests erwähnen“). Quill schreibt den Beitrag um und schickt eine neue Karte. (2 Stunden gültig.)"},
    "tg.edit.expired": {"Sie": "Die Änderungsanfrage für {pid} ist abgelaufen (2 Std.). Tippen Sie auf der Karte noch einmal auf ✏️ Ändern.",
                        "du": "Die Änderungsanfrage für {pid} ist abgelaufen (2 Std.). Tippe auf der Karte noch einmal auf ✏️ Ändern."},
    "tg.edit.got_it": "Verstanden — Quill schreibt {pid} um: „{note}“. Die neue Karte kommt gleich.",
    "tg.edit.too_late": "{pid} ist bereits {state}, die Änderung wurde nicht übernommen.",
    "tg.cards": {"Sie": {"one": "1 Beitrag: Tippen Sie auf der Karte auf ✅ Freigeben", "other": "{n} Beiträge: Tippen Sie auf den Karten auf ✅ Freigeben"},
                 "du": {"one": "1 Beitrag: Tippe auf der Karte auf ✅ Freigeben", "other": "{n} Beiträge: Tippe auf den Karten auf ✅ Freigeben"}},
    "tg.open": "Otto öffnen: {url}",
    "alert.head": "Hinweis von Otto",
    "alert.drop": "Rückgang bei {brand}: {metric} liegt bei {value}, mindestens {pct} % unter dem 7-Tage-Schnitt ({avg}). Ein Blick lohnt sich.",
    "alert.stuck": {"Sie": "„{hook}“ wurde an Meta gesendet, aber nie bestätigt. Otto versucht es nicht erneut – bitte prüfen Sie Ihre Seite.",
                    "du": "„{hook}“ wurde an Meta gesendet, aber nie bestätigt. Otto versucht es nicht erneut – bitte prüf deine Seite."},
    "alert.slot_soon": {"one": "„{hook}“ ist für {when} geplant und noch nicht freigegeben. Noch 1 Stunde.",
                        "other": "„{hook}“ ist für {when} geplant und noch nicht freigegeben. Noch {n} Stunden."},
    "alert.missed": "„{hook}“ war für {when} geplant und wurde nicht veröffentlicht. Wir prüfen, woran es lag.",
    "trial.your_business": {"Sie": "Ihr Unternehmen", "du": "dein Unternehmen"},
    "trial.price": " Tarife gibt es ab {price} im Monat.",
    "trial.a_month": "{price} im Monat",
    "trial.cta": "Tarif wählen", "trial.cta_continue": "Tarif wählen und weitermachen",
    "trial.day5.subject": {"Sie": "Noch 2 Tage in Ihrer Otto-Testphase", "du": "Noch 2 Tage in deiner Otto-Testphase"},
    "trial.day5.title": {"Sie": "Noch 2 Tage in Ihrer kostenlosen Testphase", "du": "Noch 2 Tage in deiner kostenlosen Testphase"},
    "trial.day5.lead": {"Sie": "Ihre kostenlose Otto-Testphase endet am {when}. Damit {who} ohne Pause weiter veröffentlicht, wählen Sie auf Ihrer Abrechnungsseite einen Tarif.{price} Der Tarif beginnt mit dem Ende der Testphase, und dann wird auch die erste Zahlung abgebucht. Wählen Sie keinen Tarif, wird nichts abgebucht und {who} pausiert.",
                        "du": "Deine kostenlose Otto-Testphase endet am {when}. Damit {who} ohne Pause weiter veröffentlicht, wähl auf deiner Abrechnungsseite einen Tarif.{price} Der Tarif beginnt mit dem Ende der Testphase, und dann wird auch die erste Zahlung abgebucht. Wählst du keinen Tarif, wird nichts abgebucht und {who} pausiert."},
    "trial.day7.subject_today": {"Sie": "Ihre Otto-Testphase endet heute", "du": "Deine Otto-Testphase endet heute"},
    "trial.day7.subject_tomorrow": {"Sie": "Ihre Otto-Testphase endet morgen", "du": "Deine Otto-Testphase endet morgen"},
    "trial.day7.title_today": {"Sie": "Ihre kostenlose Testphase endet heute", "du": "Deine kostenlose Testphase endet heute"},
    "trial.day7.title_tomorrow": {"Sie": "Ihre kostenlose Testphase endet morgen", "du": "Deine kostenlose Testphase endet morgen"},
    "trial.day7.lead": {"Sie": "Ihre Testphase endet um {time} Uhr ({day}). Wählen Sie jetzt einen Tarif, dann veröffentlicht {who} weiter: Der Tarif beginnt mit dem Ende der Testphase und wird dann abgebucht.{price} Ohne Tarif wird nichts abgebucht, und Beiträge und Anzeigen pausieren.",
                        "du": "Deine Testphase endet um {time} Uhr ({day}). Wähl jetzt einen Tarif, dann veröffentlicht {who} weiter: Der Tarif beginnt mit dem Ende der Testphase und wird dann abgebucht.{price} Ohne Tarif wird nichts abgebucht, und Beiträge und Anzeigen pausieren."},
    "trial.day8.subject": {"Sie": "Ihre Otto-Testphase ist beendet", "du": "Deine Otto-Testphase ist beendet"},
    "trial.day8.subject_named": {"Sie": "Ihre Otto-Testphase ist beendet – {who} ist pausiert",
                                 "du": "Deine Otto-Testphase ist beendet – {who} ist pausiert"},
    "trial.day8.title": {"Sie": "Ihre kostenlose Testphase ist beendet", "du": "Deine kostenlose Testphase ist beendet"},
    "trial.day8.lead_named": {"Sie": "Beiträge und Anzeigen für {who} sind pausiert. Ihre Arbeit – Markenprofil, Planung, Beiträge und Anzeigenvorschauen – bleibt 90 Tage gespeichert, bis {kept}. Wählen Sie einen Tarif, um dort weiterzumachen, wo Sie aufgehört haben.",
                              "du": "Beiträge und Anzeigen für {who} sind pausiert. Deine Arbeit – Markenprofil, Planung, Beiträge und Anzeigenvorschauen – bleibt 90 Tage gespeichert, bis {kept}. Wähl einen Tarif, um dort weiterzumachen, wo du aufgehört hast."},
    "trial.day8.lead": {"Sie": "Wählen Sie einen Tarif, sobald Sie starten möchten: Otto bereitet dann sofort Ihre erste Woche vor.",
                        "du": "Wähl einen Tarif, sobald du starten möchtest: Otto bereitet dann sofort deine erste Woche vor."},
    "trial.why": {"Sie": "Sie erhalten diese E-Mail, weil Sie mit {email} eine kostenlose Otto-Testphase gestartet haben.",
                  "du": "Du erhältst diese E-Mail, weil du mit {email} eine kostenlose Otto-Testphase gestartet hast."},
    "trial.terms": {"Sie": "Während der Testphase wird nichts abgebucht. Ein Tarif, den Sie wählen, beginnt automatisch mit dem Ende der Testphase und wird dann abgebucht; ohne Tarif wird nichts abgebucht und Ihr Konto pausiert. Tarife wählen und ändern Sie auf Ihrer Abrechnungsseite.",
                    "du": "Während der Testphase wird nichts abgebucht. Ein Tarif, den du wählst, beginnt automatisch mit dem Ende der Testphase und wird dann abgebucht; ohne Tarif wird nichts abgebucht und dein Konto pausiert. Tarife wählst und änderst du auf deiner Abrechnungsseite."},
    "trial.line.posts": "{posts} Beiträge im Monat, davon {reels} Reels",
    "trial.line.paid": "Anzeigenkampagnen auf {nets}",
    "trial.line.cap": ", Werbebudget bis {cap} im Monat",
    "trial.line.matrix": "Monatliche Anzeigenmatrix: {preset}",
    "preset.micro": "4 Konzepte × 5 Stile", "preset.launch": "6 Konzepte × 6 Stile", "preset.scale": "6 Konzepte × 8 Stile",
    "rec.connect_meta.title": "Instagram und Facebook für {name} verbinden",
    "rec.connect_meta.why": {"Sie": "Otto bereitet die erste Woche schon vor, kann aber erst veröffentlichen, wenn Sie über die Anmeldung bei Meta Ihre Seite und Ihr Instagram-Konto verknüpft haben. Sie wählen beides aus; ohne Ihre Freigabe wird nichts veröffentlicht.",
                             "du": "Otto bereitet die erste Woche schon vor, kann aber erst veröffentlichen, wenn du über die Anmeldung bei Meta deine Seite und dein Instagram-Konto verknüpft hast. Du wählst beides aus; ohne deine Freigabe wird nichts veröffentlicht."},
    "rec.connect_meta.impact": "Damit Otto veröffentlichen kann",
    "rec.pair_telegram.title": "Telegram für {name} koppeln",
    "rec.pair_telegram.why": {"Sie": "Freigaben, der Bericht um 07:35 Uhr und Hinweise kommen in Telegram an, sobald Ihr Telefon gekoppelt ist. Bis dahin wartet alles in der App.",
                              "du": "Freigaben, der Bericht um 07:35 Uhr und Hinweise kommen in Telegram an, sobald dein Telefon gekoppelt ist. Bis dahin wartet alles in der App."},
    "rec.pair_telegram.impact": "Freigeben vom Telefon aus",
    "rec.connect_google.title": "Google Ads für {name} verbinden",
    "rec.connect_google.why": {"Sie": "Suchanzeigen brauchen Ihr Google-Ads-Konto, verknüpft über die Anmeldung bei Google.",
                               "du": "Suchanzeigen brauchen dein Google-Ads-Konto, verknüpft über die Anmeldung bei Google."},
    "rec.connect_google.impact": {"Sie": "Suchanzeigen im Rahmen Ihres Budgets", "du": "Suchanzeigen im Rahmen deines Budgets"},
    "rec.compliance_hold.title": "Wegen der Regeln zurückgehalten: {subject}",
    "rec.compliance_hold.why": {"Sie": "Otto hat das zurückgehalten, bevor es Sie erreicht hat: Es verstößt gegen eine Werberegel für Ihre Branche oder Ihr Land. Passen Sie es in der App an, bevor es online gehen kann.",
                                "du": "Otto hat das zurückgehalten, bevor es dich erreicht hat: Es verstößt gegen eine Werberegel für deine Branche oder dein Land. Pass es in der App an, bevor es online gehen kann."},
    "rec.compliance_hold.impact": {"Sie": "Schützt Ihr Werbekonto und Ihre Marke vor Regelverstößen", "du": "Schützt dein Werbekonto und deine Marke vor Regelverstößen"},
    "rec.check_live.title": "Bitte prüfen, ob das online ist: {hook}",
    "rec.check_live.why": {"Sie": "Otto hat diesen Beitrag an Meta gesendet, aber nie eine Bestätigung erhalten, und versucht es nicht selbst erneut. Prüfen Sie Ihre Seite: Ist er online, markieren Sie ihn als veröffentlicht; wenn nicht, schicken Sie ihn zurück in die Prüfung.",
                           "du": "Otto hat diesen Beitrag an Meta gesendet, aber nie eine Bestätigung erhalten, und versucht es nicht selbst erneut. Prüf deine Seite: Ist er online, markiere ihn als veröffentlicht; wenn nicht, schick ihn zurück in die Prüfung."},
    "rec.check_live.impact": "Verhindert einen doppelten Beitrag",
    "rec.missed.title": "Nicht veröffentlicht: {hook}",
    "rec.missed.why": {"Sie": "Dieser Beitrag war für {when} freigegeben, ist aber nicht online gegangen. Wählen Sie in der App einen neuen Termin.",
                       "du": "Dieser Beitrag war für {when} freigegeben, ist aber nicht online gegangen. Wähl in der App einen neuen Termin."},
    "rec.missed.impact": {"Sie": "Damit Ihr Kalender stimmt", "du": "Damit dein Kalender stimmt"},
    "rec.linkedin.title": "Selbst auf LinkedIn posten: {hook}",
    "rec.linkedin.why": {"Sie": "Dieser Beitrag ist für LinkedIn freigegeben ({when}), wo Otto noch nicht veröffentlichen kann. Posten Sie ihn selbst; der Text liegt in der App bereit.",
                         "du": "Dieser Beitrag ist für LinkedIn freigegeben ({when}), wo Otto noch nicht veröffentlichen kann. Poste ihn selbst; der Text liegt in der App bereit."},
    "rec.linkedin.impact": "Der Beitrag erscheint trotzdem pünktlich",
    "rec.publish_failed.title": "Veröffentlichung 3× fehlgeschlagen: {hook}",
    "rec.publish_failed.why": "Meta hat diesen Beitrag dreimal abgelehnt; er bleibt unveröffentlicht, bis das Problem gelöst ist. Die Details stehen in der App.",
    "rec.publish_failed.impact": "Der Beitrag bleibt offline, bis das Problem gelöst ist",
    "rec.double_down.title": "Nächste Woche mehr „{pillar}“",
    "rec.double_down.why": "Bester Beitrag: „{hook}“, Reichweite {reach}, {saves}-mal gespeichert. {pillar} stellt {k} der besten 5.",
    "rec.double_down.impact": "Die nächste Runde baut auf dem auf, was funktioniert",
    "rec.pause.title": "„{campaign}“ pausieren: seit drei Tagen über dem Zielpreis pro Ergebnis",
    "rec.pause.why": "Ziel sind {target} pro Ergebnis; diese Kampagne liegt seit drei Tagen darüber. Eine Pause verschiebt das Budget zur stärksten Kampagne.",
    "rec.pause.impact": "Stoppt die Verluste noch am selben Tag",
}

CATALOGS = {"en": EN, "nl": NL, "de": DE}


# ---------------------------------------------------------------------------------------------------------------- core

def norm_lang(code):
    """"nl" / "NL" / "nl-BE" / "de_AT" → a catalog language; anything else → en."""
    c = str(code or "").strip().lower().replace("_", "-").split("-")[0]
    return c if c in CATALOGS else DEFAULT


COMMS_LANGS = {"en": "English", "nl": "Nederlands", "de": "Deutsch"}     # the choice the client is offered, in its own words


def normalize_comms_lang(v):
    """A value for brands[].comms_lang from a client / the owner: "en" | "nl" | "de" (any case). ValueError otherwise."""
    x = str(v if v is not None else "").strip().lower()
    if x not in COMMS_LANGS:
        raise ValueError("comms_lang must be en, nl or de")
    return x


def lang_of(b):
    """The language a brand's client messages use: brands[].comms_lang when it names a catalog, else English. Never the
    brand's content language (brands[].lang / the site scan): that is what its posts are written in."""
    v = str((b or {}).get("comms_lang") or "").strip().lower()
    return v if v in CATALOGS else DEFAULT


_DU = re.compile(r"\b(?:du|dich|dir|dein|deine|deinen|deinem|deiner|deines|euch|euer|eure)\b", re.I)
_SIE = re.compile(r"\b(?:Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihres)\b")
_voice_cache = {}


def voice_register(bid):
    """"informal" when the brand's own site (scan text, headings, description) speaks du clearly more than Sie; else
    "formal". Cached per process."""
    if bid in _voice_cache:
        return _voice_cache[bid]
    s = ap.scan_of(bid) if bid else {}
    text = " ".join([str(s.get("text_sample") or ""), " ".join(str(h) for h in s.get("headings") or []),
                     str((s.get("identity") or {}).get("description") or "")])
    du, sie = len(_DU.findall(text)), len(_SIE.findall(text))
    reg = INFORMAL if du >= 3 and du > 1.5 * sie else FORMAL
    _voice_cache[bid] = reg
    return reg


def register_of(b, lang=None):
    """formal | informal for this brand's German messages: brands[].address when set, else the brand's own voice."""
    b = b or {}
    raw = str(b.get("address") or "").strip().lower()
    if raw in ("formal", "sie", "u"):
        return FORMAL
    if raw in ("informal", "du", "je"):
        return INFORMAL
    if (lang or lang_of(b)) != "de":
        return INFORMAL if (lang or lang_of(b)) == "nl" else FORMAL
    return voice_register(b.get("id"))


def _pick(v, register, n):
    if isinstance(v, dict) and ("Sie" in v or "du" in v):
        v = v.get(REGISTER_KEYS.get(register, "Sie")) or v.get("Sie") or v.get("du")
    if isinstance(v, dict):
        v = v.get("one" if n == 1 else "other") or v.get("other") or ""
    return v


class Tr:
    """Translator + formatter for one language / register. tr("key", n=3, name=…) → text."""

    def __init__(self, lang=DEFAULT, register=FORMAL):
        self.lang = norm_lang(lang)
        self.register = register if register in (FORMAL, INFORMAL) else FORMAL
        self.f = FMT[self.lang]

    @classmethod
    def for_brand(cls, b):
        lang = lang_of(b)
        return cls(lang, register_of(b, lang))

    def __repr__(self):
        return f"Tr({self.lang!r}, {self.register!r})"

    def has(self, key):
        return key in CATALOGS[self.lang] or key in EN

    def __call__(self, key, n=None, **kw):
        v = CATALOGS[self.lang].get(key)
        if v is None:
            v = EN.get(key)
        if v is None:
            raise KeyError(key)
        text = _pick(v, self.register, n)
        if n is not None:
            kw.setdefault("n", self.num(n))
        return text.format(**kw) if kw or "{" in text else text

    # ---- formatting
    def num(self, v, digits=0):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return str(v)
        s = f"{x:,.{digits}f}"
        if self.f["grp"] != ",":
            s = s.replace(",", "\x00").replace(".", self.f["dec"]).replace("\x00", self.f["grp"])
        return s

    def money(self, v, code="EUR", digits=None):
        if v is None:
            return "—"
        x = float(v)
        if digits is None:
            digits = 0 if abs(x - round(x)) < 0.005 else 2
        code = (ap.currency_code(code) or "EUR") if code else "EUR"
        num = self.num(abs(x), digits)
        sym = SYMBOLS.get(code)
        out = self.f["money"].format(sym=sym, num=num) if sym else self.f["money_code"].format(code=code, num=num)
        return ("-" + out) if x < 0 else out

    def pct(self, v, digits=1):
        return self.f["pct"].format(num=self.num(v, digits))

    def day(self, dt):
        return self.f["day"].format(wd=self.f["days"][dt.weekday()], d=dt.day, mon=self.f["months"][dt.month - 1])

    def long_day(self, dt):
        return self.f["day_long"].format(wdl=self.f["days_long"][dt.weekday()], d=dt.day, monl=self.f["months_long"][dt.month - 1])

    def day_month(self, dt):
        return self.f["day_month"].format(d=dt.day, mon=self.f["months"][dt.month - 1])

    @staticmethod
    def time(dt):
        return f"{dt:%H:%M}"

    def day_time(self, dt):
        return f"{self.day(dt)} · {self.time(dt)}"

    def day_at(self, dt):
        return self.f["day_at"].format(day=self.day(dt), time=self.time(dt))

    def weekday(self, dt, long=False):
        return self.f["days_long" if long else "days"][dt.weekday()]

    def initial(self, dt):
        return self.f["days"][dt.weekday()][0].upper()

    def month(self, ym):
        """"2026-11" | a date | a month number → "November" / "november" / "November"."""
        if isinstance(ym, (date, datetime)):
            m = ym.month
        elif isinstance(ym, int):
            m = ym
        else:
            mm = re.fullmatch(r"\d{4}-(\d{2})", str(ym or "").strip())
            if not mm:
                return str(ym or "")
            m = int(mm.group(1))
        return self.f["months_long"][m - 1] if 1 <= m <= 12 else str(ym)

    def city(self, tz):
        name = getattr(tz, "key", "") or str(tz or "")
        city = name.rsplit("/", 1)[-1].replace("_", " ") if "/" in name else name
        return (CITIES.get(city) or {}).get(self.lang, city)

    def join(self, items):
        items = [x for x in items if x]
        if len(items) <= 1:
            return "".join(items)
        return ", ".join(items[:-1]) + f" {self.f['and']} " + items[-1]


def tr(b):
    """The translator for a brand record."""
    return Tr.for_brand(b)


# ---------------------------------------------------------------------------------------------------------------- checks

def fields(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def _leaves(v):
    """(register, plural, text) for every text a catalog value can produce."""
    out = []
    regs = [(k, v[k]) for k in ("Sie", "du") if k in v] if isinstance(v, dict) and ("Sie" in v or "du" in v) else [(None, v)]
    for reg, x in regs:
        if isinstance(x, dict):
            out += [(reg, k, x[k]) for k in ("one", "other") if k in x]
        else:
            out.append((reg, None, x))
    return out


def problems():
    """Catalog completeness against English: every key in nl and de, plural keys plural in both, German register
    pairs complete, the same placeholders as English (a plural's "one" form may write the 1 out instead of {n})."""
    out = []
    for lang in ("nl", "de"):
        cat = CATALOGS[lang]
        for key, ev in EN.items():
            if key not in cat:
                out.append(f"{lang}: missing {key}")
                continue
            v = cat[key]
            if isinstance(v, dict) and ("Sie" in v or "du" in v):
                if lang != "de":
                    out.append(f"{lang}: {key} has German register variants")
                if not ("Sie" in v and "du" in v):
                    out.append(f"{lang}: {key} needs both Sie and du")
            e_plural = isinstance(ev, dict)
            for reg, plural, text in _leaves(v):
                if not isinstance(text, str) or not text.strip():
                    out.append(f"{lang}: {key} is empty")
                    continue
                if e_plural and plural is None:
                    out.append(f"{lang}: {key} must have one / other")
                    continue
                if not e_plural and plural is not None:
                    out.append(f"{lang}: {key} is plural, English is not")
                    continue
                want, got = fields(ev[plural] if e_plural else ev), fields(text)
                if plural == "one":                       # "1 post" may write the one out instead of {n}
                    want, got = want - {"n"}, got - {"n"}
                if got != want:
                    out.append(f"{lang}: {key}{'/' + plural if plural else ''}{'/' + reg if reg else ''} placeholders {sorted(got)} ≠ en {sorted(want)}")
        for key in cat:
            if key not in EN:
                out.append(f"{lang}: {key} is not in the English catalog")
    for key, ev in EN.items():
        if isinstance(ev, dict) and not ({"one", "other"} <= set(ev)):
            out.append(f"en: {key} must have one / other")
    return out


# ---------------------------------------------------------------------------------------------------------------- CLI

def set_comms_lang(bid, value, via="cli"):
    v = normalize_comms_lang(value)
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            raise KeyError(bid)
        before = lang_of(b)
        b["comms_lang"] = v
        b["comms_lang_set"] = {"at": ap.now_iso(), "via": via}
    return before, v


def _set_address(bid, value):
    v = str(value or "").strip().lower()
    if v not in ("formal", "informal", "auto", "sie", "du"):
        raise SystemExit("address must be formal (Sie), informal (du) or auto")
    v = {"sie": "formal", "du": "informal"}.get(v, v)
    with ap.transaction() as d:
        b = ap.brand(d, bid)
        if b is None:
            raise SystemExit(f"unknown brand {bid}")
        if v == "auto":
            b.pop("address", None)
        else:
            b["address"] = v
        b["address_set"] = {"at": ap.now_iso(), "via": "cli"}
        reg = register_of(b)
    print(f"{bid}: German messages use {'Sie' if reg == FORMAL else 'du'}" + (" (from the brand's own voice)" if v == "auto" else ""))


def main(a):
    cmd = a[0] if a else ""
    if cmd == "check":
        p = problems()
        for x in p:
            print(x)
        n = sum(1 for _ in EN)
        print(f"{n} keys · nl {len(NL)} · de {len(DE)} · {len(p)} problem(s)")
        return 1 if p else 0
    if cmd == "show" and len(a) > 1:
        b = ap.brand(ap.load(), a[1])
        if not b:
            raise SystemExit(f"unknown brand {a[1]}")
        t = Tr.for_brand(b)
        now = datetime.now(ap.brand_tz(b))
        print(f"{a[1]}: {t.lang} (brands[].comms_lang {b.get('comms_lang') or 'unset → en'}) · "
              f"{'Sie' if t.register == FORMAL else 'du' if t.lang == 'de' else 'je' if t.lang == 'nl' else '—'}"
              f" · brands[].address {b.get('address') or 'auto'} · posts in {ap.brand_lang(b)}")
        print(f"  {t('report.subject', day=t.day(now), name=b.get('name') or b['id'])}")
        print(f"  {t.day_time(now)} · {t.money(1234.5, ap.brand_currency(ap.load(), a[1]))} · {t.num(12480)}")
        print(f"  {t('report.sum.clear')}")
        return 0
    if cmd == "lang" and len(a) > 2:
        try:
            before, v = set_comms_lang(a[1], a[2])
        except KeyError:
            raise SystemExit(f"unknown brand {a[1]}")
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"{a[1]}: e-mails and reports in {COMMS_LANGS[v]} (was {COMMS_LANGS[before]})")
        return 0
    if cmd == "address" and len(a) > 2:
        _set_address(a[1], a[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
