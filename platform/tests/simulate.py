#!/usr/bin/env python3
"""Otto launch simulation — five synthetic businesses through the whole lifecycle, offline, in dry / faked mode.

  cd platform && python3 tests/simulate.py [--keep] [--json <results.json>] [--verbose]

Everything runs in a throwaway workspace (OTTO_DATA / OTTO_HTML / OTTO_BRANDS / OTTO_ASSETS / OTTO_PUBLIC_ASSETS /
OTTO_SECRETS / OTTO_MOTION_ROOT all point into a temp dir): never the real platform/data.json, brands/ or index.html.
The fixture websites are local HTML files served by http.server on 127.0.0.1; the scanner's public-IP guard is relaxed
for exactly that address (as tests/test_engine.py does), so a redirect to a private IP is still refused.

No real network: every process (this one and every subprocess, via a sitecustomize guard on PYTHONPATH) refuses DNS
and connections to anything but loopback. Meta Graph, Telegram, Google OAuth / Ads and the OpenClaw sender are fakes
that record calls. A simulated clock (module-level datetime/date replacements) moves time forward: cards are sent on
Sep 30, posts publish on Oct 1, paid flights launch on Oct 1, the month review goes out on Nov 1.

Output: a business × step matrix (PASS / WARN / FAIL / SKIP), every note, and a JSON dump. Exit code 1 if any FAIL.
"""
import contextlib, hashlib, http.server, io, json, os, re, shutil, subprocess, sys, tempfile, threading, time, traceback
import urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PLATFORM = Path(__file__).resolve().parent.parent
REPO = PLATFORM.parent
TESTS = Path(__file__).resolve().parent
_real_datetime, _real_date = datetime, date

# ============================================================================================
# fixture businesses (synthetic — names, domains, people and numbers are invented)
# ============================================================================================

CSS = """body{{font-family:'{font}',sans-serif;background:{bg};color:{ink}}}
a,.btn{{color:{c1}}} .btn{{background:{c1};border-color:{c1}}} .accent{{color:{c2}}} h1,h2{{color:{c1}}}
.badge{{background:{c2}}} .hero{{background:linear-gradient({c1},{c2})}} footer{{background:{ink};color:{bg}}}
.card{{border:1px solid {c1}}} .tag{{color:{c2};border-color:{c2}}} .cta{{background:{c2}}}"""


def page(lang, title, desc, body, nav, site_name, theme, font, css="/style.css", rtl=False, hreflang=(), extra_head=""):
    links = "".join(f'<a href="{h}">{t}</a> ' for h, t in nav)
    alts = "".join(f'<link rel="alternate" hreflang="{l}" href="{h}">' for l, h in hreflang)
    fam = font.replace(" ", "+")
    return f"""<!doctype html><html lang="{lang}"{' dir="rtl"' if rtl else ''}><head><meta charset="utf-8">
<title>{title}</title><meta name="description" content="{desc}"><meta property="og:site_name" content="{site_name}">
<meta property="og:title" content="{title}"><meta property="og:image" content="/img/og.jpg"><meta name="theme-color" content="{theme}">
<link rel="stylesheet" href="{css}"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={fam}:wght@400;700&display=swap">
<link rel="apple-touch-icon" href="/img/touch.png">{alts}{extra_head}</head>
<body><header><img src="/img/logo.svg" alt="{site_name} logo" class="site-logo"><nav>{links}</nav></header>
<main>{body}</main></body></html>"""


def site_spreebogen():
    nav = [("/leistungen", "Leistungen"), ("/preise", "Preise"), ("/ueber-uns", "Über uns"), ("/bewertungen", "Bewertungen"),
           ("/kontakt", "Kontakt")]
    kw = dict(lang="de", site_name="Zahnarztpraxis Spreebogen", theme="#0E7C86", font="Source Sans 3", nav=nav)
    home = """<h1>Ihr Zahnarzt in Berlin-Mitte – entspannt, modern und ehrlich</h1>
<p>Wir sind eine moderne Zahnarztpraxis am Spreebogen. Unser Team aus fünf Zahnärztinnen und Zahnärzten kümmert sich um
Prophylaxe, Implantate, unsichtbare Zahnspangen und die Behandlung von Angstpatienten. Termine bekommen Sie online oder per
Telefon, auch abends und am Samstag. Wir erklären jeden Schritt, bevor wir anfangen, und nehmen uns Zeit für die Beratung.</p>
<h2>Unsere Leistungen</h2><ul><li>Professionelle Zahnreinigung ab 89 €</li><li>Bleaching ab 299 €</li>
<li>Aligner-Behandlung ab 2.900 €</li><li>Implantat mit Krone ab 2.450 €</li></ul>
<h2>Warum Patienten zu uns kommen</h2><p>Seit 2009 in Berlin-Mitte. Über 4.800 Google-Bewertungen mit 4,9 Sternen.
Zertifiziertes Qualitätsmanagement nach ISO 9001. Barrierefreie Praxis mit Aufzug.</p>
<div class="review">„Ich hatte jahrelang Angst vor dem Zahnarzt. Hier wurde mir alles in Ruhe erklärt und die Behandlung war völlig schmerzfrei.“ – Julia, 34</div>
<div class="review">„Termin am Samstag, keine Wartezeit, und die Zahnreinigung war gründlich wie nie. Klare Empfehlung für alle in Mitte.“ – Murat, 41</div>
<h2>Termin buchen</h2><p>Online-Termin in zwei Minuten oder <a href="tel:+493012345678">030 1234 5678</a> ·
<a href="mailto:praxis@spreebogen-zahnarzt.example">praxis@spreebogen-zahnarzt.example</a></p>
<footer><a href="https://www.instagram.com/zahnarzt.spreebogen.example/">Instagram</a> <a href="https://www.facebook.com/zahnarztspreebogenexample">Facebook</a></footer>
<script>fbq('init','111222333'); fbq('track','PageView');</script>"""
    sub = {
        "/leistungen": ("Leistungen | Zahnarztpraxis Spreebogen", "<h1>Leistungen</h1><h2>Prophylaxe und Zahnreinigung</h2><p>Die professionelle Zahnreinigung dauert bei uns 60 Minuten und kostet ab 89 €. Für Angstpatienten bieten wir Lachgas und extra lange Termine an.</p><h2>Implantate</h2><p>Implantat mit Krone ab 2.450 €, inklusive 3D-Planung.</p>"),
        "/preise": ("Preise | Zahnarztpraxis Spreebogen", "<h1>Preise und Zuzahlungen</h1><p>Zahnreinigung ab 89 €, Bleaching ab 299 €, Aligner ab 2.900 €, Veneers ab 1.150 € pro Zahn. Ratenzahlung ohne Zinsen möglich.</p>"),
        "/ueber-uns": ("Über uns | Zahnarztpraxis Spreebogen", "<h1>Unser Team</h1><p>Fünf Zahnärztinnen und Zahnärzte, zwölf Prophylaxe-Fachkräfte und ein Praxishund. Seit 2009 für Sie da.</p>"),
        "/bewertungen": ("Bewertungen | Zahnarztpraxis Spreebogen", "<h1>Das sagen unsere Patienten</h1><blockquote>„Endlich eine Praxis, in der man nicht wie am Fließband behandelt wird. Ich komme seit sechs Jahren und würde nie wechseln.“ – Anna, 52</blockquote>"),
        "/kontakt": ("Kontakt | Zahnarztpraxis Spreebogen", "<h1>Kontakt</h1><p>Am Spreebogen 1, 10557 Berlin. Mo–Fr 8–20 Uhr, Sa 9–14 Uhr.</p>"),
    }
    css = CSS.format(font="Source Sans 3", bg="#FDF6EC", ink="#1B2B34", c1="#0E7C86", c2="#F26B5B")
    return build_site(kw, "Zahnarztpraxis Spreebogen | Ihr Zahnarzt in Berlin-Mitte",
                      "Moderne Zahnmedizin in Berlin-Mitte: Prophylaxe, Implantate, Aligner und Angstpatienten. Termine online buchen.",
                      home, sub, css)


def site_ondaviva():
    nav = [("/aulas-e-precos", "Aulas e preços"), ("/sobre-nos", "Sobre nós"), ("/testemunhos", "Testemunhos"),
           ("/contacto", "Contacto"), ("/en/", "English")]
    kw = dict(lang="pt-PT", site_name="Onda Viva Surf School", theme="#FF7A1A", font="Poppins", nav=nav,
              hreflang=[("pt-PT", "/"), ("en", "/en/")])
    home = """<h1>Aprende a surfar na Costa da Caparica</h1>
<p>A Onda Viva é uma escola de surf certificada pela federação, a 20 minutos de Lisboa. Damos aulas de surf para iniciantes,
famílias e grupos, todos os dias do ano, com fatos e pranchas incluídos. Os nossos instrutores são nadadores-salvadores
e falam português, inglês e espanhol.</p>
<h2>Aulas e preços</h2><ul><li>Aula de grupo (2h) — 35 €</li><li>Pack 5 aulas — 150 €</li><li>Aula privada — 60 €</li>
<li>Surf camp de uma semana — 1.190 €</li></ul>
<div class="testimonial">"Nunca tinha estado numa prancha e no fim da primeira aula já estava de pé. Os instrutores são pacientes e divertidos." — Inês, Lisboa</div>
<div class="testimonial">"Best surf lesson we had in Portugal. Great instructors, all the gear included and the beach is beautiful." — Tom, Bristol</div>
<p>Mais de 12.000 alunos desde 2012 · Seguro incluído · 4,9 ★ no Google</p>
<p><a href="tel:+351912345678">+351 912 345 678</a> · <a href="https://wa.me/351912345678">WhatsApp</a> ·
<a href="https://www.instagram.com/ondaviva.surf.example/">Instagram</a></p>"""
    sub = {
        "/aulas-e-precos": ("Aulas e preços | Onda Viva", "<h1>Aulas e preços</h1><p>Aula de grupo 35 €, pack de 5 aulas 150 €, aula privada 60 €, surf camp 1.190 €. Crianças a partir dos 7 anos.</p>"),
        "/sobre-nos": ("Sobre nós | Onda Viva", "<h1>Sobre nós</h1><p>Fundada em 2012 por dois irmãos da Caparica. Escola certificada, seguro incluído em todas as aulas.</p>"),
        "/testemunhos": ("Testemunhos | Onda Viva", "<h1>Testemunhos</h1><div class=\"testimonial\">\"Levei os meus filhos e agora querem voltar todos os fins de semana. Equipa fantástica e muito segura.\" — Rui, Almada</div>"),
        "/contacto": ("Contacto | Onda Viva", "<h1>Contacto</h1><p>Praia do CDS, Costa da Caparica. Aberto todos os dias das 8h às 19h.</p>"),
        "/en/": ("Surf lessons near Lisbon | Onda Viva", "<h1>Learn to surf near Lisbon</h1><p>Group lesson €35, 5-lesson pack €150, private lesson €60. All gear included.</p>"),
    }
    css = CSS.format(font="Poppins", bg="#FFFFFF", ink="#12303A", c1="#0A6E8A", c2="#FF7A1A")
    return build_site(kw, "Onda Viva Surf School | Aulas de surf na Costa da Caparica",
                      "Escola de surf certificada perto de Lisboa. Aulas para iniciantes, famílias e grupos com material incluído.",
                      home, sub, css)


def site_grachten():
    nav = [("/collections/koffiebonen", "Koffiebonen"), ("/products/ethiopia-guji", "Ethiopia Guji"), ("/pages/over-ons", "Over ons"),
           ("/pages/reviews", "Reviews"), ("/pages/contact", "Contact"), ("/cart", "Winkelwagen")]
    kw = dict(lang="nl", site_name="Grachten Koffiebranders", theme="#C8553D", font="DM Sans", nav=nav,
              hreflang=[("nl", "/"), ("en", "/en/")],
              extra_head='<script src="https://cdn.shopify.com/s/files/1/0000/0001/t/1/assets/theme.js" defer></script>')
    home = """<h1>Versgebrande specialty koffie uit Amsterdam</h1>
<p>Wij branden elke dinsdag en vrijdag kleine batches specialty koffie in onze branderij aan de Keizersgracht. Direct gehandeld,
eerlijk betaald aan de boeren, en binnen 48 uur bij je thuis. Bonen of gemalen, voor filter en espresso.</p>
<div class="product-card"><h3>Ethiopia Guji — natural</h3><span class="price">€14,50</span><button>In winkelwagen</button></div>
<div class="product-card"><h3>Colombia Huila — washed</h3><span class="price">€13,95</span><button>In winkelwagen</button></div>
<div class="product-card"><h3>Espresso Blend Keizer</h3><span class="price">€12,50</span><button>In winkelwagen</button></div>
<p>Koffie-abonnement vanaf €24,00 per maand · Gratis verzending vanaf €40 · Vandaag besteld voor 16:00, morgen in huis.</p>
<div class="review">"Beste koffie die ik thuis ooit heb gezet. De Guji ruikt naar bosbessen, echt waar. Abonnement loopt nu een jaar." — Sanne, Utrecht</div>
<div class="review">"Snelle levering, mooie verpakking en de espresso blend is perfect voor mijn Gaggia. Ik bestel niets anders meer." — Joost, Haarlem</div>
<p>4,8 ★ uit 2.100 reviews · Specialty Coffee Association member · Veilig afrekenen met iDEAL</p>
<footer><a href="https://www.instagram.com/grachtenkoffie.example/">Instagram</a> <a href="mailto:hallo@grachtenkoffie.example">hallo@grachtenkoffie.example</a></footer>
<script>fbq('init','444555666');</script>"""
    sub = {
        "/collections/koffiebonen": ("Koffiebonen | Grachten", "<h1>Alle koffiebonen</h1><p>Ethiopia Guji €14,50 · Colombia Huila €13,95 · Kenya Nyeri €16,50 · Decaf Brazil €12,95. Gratis verzending vanaf €40.</p>"),
        "/products/ethiopia-guji": ("Ethiopia Guji | Grachten", "<h1>Ethiopia Guji — natural</h1><p>Bosbes, jasmijn, melkchocolade. 250 gram €14,50, 1 kilo €49,00. Vers gebrand op dinsdag.</p>"),
        "/pages/over-ons": ("Over ons | Grachten", "<h1>Over ons</h1><p>Sinds 2016 branden we aan de gracht. Kleine batches, directe handel, geen koffie ouder dan drie weken.</p>"),
        "/pages/reviews": ("Reviews | Grachten", "<h1>Reviews</h1><div class=\"review\">\"Het abonnement is de beste beslissing van dit jaar. Elke twee weken verse bonen in de brievenbus.\" — Fatima, Rotterdam</div>"),
        "/pages/contact": ("Contact | Grachten", "<h1>Contact</h1><p>Keizersgracht 100, Amsterdam. Proeverij elke zaterdag.</p>"),
    }
    css = CSS.format(font="DM Sans", bg="#F4E9DC", ink="#1E1611", c1="#3B2A20", c2="#C8553D")
    return build_site(kw, "Grachten Koffiebranders | Specialty koffie online bestellen",
                      "Versgebrande specialty koffie uit Amsterdam. Bonen en abonnementen, gratis verzending vanaf €40.",
                      home, sub, css)


def site_ofek():
    nav = [("/about", "אודות"), ("/courses/art-therapy", "טיפול באמנות"), ("/courses/movement", "טיפול בתנועה"),
           ("/testimonials", "בוגרים מספרים"), ("/contact", "צור קשר")]
    kw = dict(lang="he", site_name="מכללת אופק", theme="#6C3FB5", font="Heebo", nav=nav, rtl=True)
    home = """<h1>הופכים את האהבה ליצירה למקצוע טיפולי</h1>
<p>מכללת אופק מכשירה מטפלות ומטפלים באמנות, בתנועה ובדרמה כבר שמונה עשרה שנה. הלימודים מתקיימים בתל אביב ובזום, פעמיים
בשבוע, עם הדרכה קלינית, פרקטיקום בקהילה וליווי אישי עד ההסמכה. הסגל שלנו כולל מטפלים ותיקים, אמנים וחוקרים, והקבוצות קטנות
כדי שלכל סטודנט יהיה מקום לצמוח. בוגרי המכללה עובדים בבתי ספר, במרפאות, בעמותות ובקליניקות פרטיות בכל הארץ.</p>
<h2>מסלולי לימוד</h2><ul><li>תעודת מטפל/ת באמנות — שכר לימוד ₪18,500 לשנה</li><li>קורס מבוא לטיפול בתנועה — 2,900 ₪</li>
<li>סדנת היכרות — ₪180</li></ul>
<div class="testimonial">"בגיל 41 החלטתי לעשות הסבה מקצועית. היום יש לי קליניקה משלי בהרצליה ואני עובדת עם ילדים ונוער." — מיכל, בוגרת 2022</div>
<div class="testimonial">"הלימודים באופק נתנו לי שפה חדשה לעבודה עם אנשים. הליווי של המנחים היה אישי ומדויק לאורך כל הדרך." — יואב, בוגר 2021</div>
<p>יותר מ-3,200 בוגרים · מוסד לימודים מוכר · מלגות ופריסת תשלומים · הכשרה מעשית בקהילה</p>
<p><a href="tel:+97235551234">03-555-1234</a> · <a href="https://wa.me/972501234567">וואטסאפ</a> ·
<a href="https://www.facebook.com/ofekcollege.example">פייסבוק</a></p>"""
    sub = {
        "/about": ("אודות | מכללת אופק", "<h1>אודות המכללה</h1><p>מכללת אופק נוסדה ב-2008 ומכשירה מטפלים באמנויות. הלימודים כוללים תיאוריה, סדנאות חווייתיות והדרכה קלינית.</p>"),
        "/courses/art-therapy": ("טיפול באמנות | מכללת אופק", "<h1>לימודי טיפול באמנות</h1><p>תוכנית תעודה של שנתיים, שכר לימוד ₪18,500 לשנה, פריסה עד 12 תשלומים. פתיחת מחזור באוקטובר.</p>"),
        "/courses/movement": ("טיפול בתנועה | מכללת אופק", "<h1>טיפול בתנועה</h1><p>קורס מבוא של 12 מפגשים ב-2,900 ₪. מתאים לרקדנים, מורים ואנשי חינוך.</p>"),
        "/testimonials": ("בוגרים מספרים | מכללת אופק", "<h1>בוגרים מספרים</h1><div class=\"testimonial\">\"הגעתי מעולם ההייטק ולא האמנתי שאפשר לשלב יצירה ועבודה טיפולית. היום זו העבודה שלי.\" — נועה, בוגרת 2023</div>"),
        "/contact": ("צור קשר | מכללת אופק", "<h1>צור קשר</h1><p>רחוב הארבעה 10, תל אביב. ימים א׳–ה׳ 9:00–19:00.</p>"),
    }
    css = CSS.format(font="Heebo", bg="#FFFDF7", ink="#221B33", c1="#6C3FB5", c2="#F5B700")
    return build_site(kw, "מכללת אופק | לימודי טיפול באמנות בתל אביב",
                      "לימודי טיפול באמנות, בתנועה ובדרמה בתל אביב. הסבה מקצועית למטפלים, מסלולי תעודה והדרכה קלינית.",
                      home, sub, css)


def site_lume():
    nav = [("/chi-siamo", "Chi siamo"), ("/progetti", "Progetti"), ("/servizi", "Servizi"), ("/contatti", "Contatti")]
    kw = dict(lang="it", site_name="Studio Lume Interni", theme="#B08D57", font="Cormorant Garamond", nav=nav)
    home = """<h1>Interni su misura a Milano</h1>
<p>Studio Lume progetta case e uffici a Milano dal 2011: ristrutturazioni chiavi in mano, arredamento su misura e consulenza
sull'illuminazione. Seguiamo ogni progetto dal primo sopralluogo alla consegna delle chiavi, con un unico referente e un
cronoprogramma condiviso. Interior design per appartamenti, loft e negozi.</p>
<h2>Servizi</h2><ul><li>Progettazione d'interni</li><li>Ristrutturazione chiavi in mano</li><li>Arredo su misura e cucine</li><li>Home staging</li></ul>
<blockquote>"Hanno trasformato un bilocale buio in Porta Romana in una casa piena di luce. Tempi rispettati e nessuna sorpresa sul budget." — Chiara e Luca</blockquote>
<p>Preventivo gratuito entro 48 ore · Oltre 140 progetti realizzati · Pubblicati su riviste di design</p>
<footer><a href="https://www.instagram.com/studiolume.example/">Instagram</a> <a href="https://www.pinterest.it/studiolume.example/">Pinterest</a>
<a href="mailto:ciao@studiolume.example">ciao@studiolume.example</a></footer>"""
    sub = {
        "/chi-siamo": ("Chi siamo | Studio Lume", "<h1>Chi siamo</h1><p>Architetti e interior designer a Milano dal 2011. Ogni progetto parte dalla luce naturale della casa.</p>"),
        "/progetti": ("Progetti | Studio Lume", "<h1>Progetti</h1><h2>Loft in Isola</h2><h2>Bilocale a Porta Romana</h2><h2>Boutique in Brera</h2>"),
        "/servizi": ("Servizi | Studio Lume", "<h1>Servizi</h1><p>Progettazione, ristrutturazione chiavi in mano, direzione lavori, arredo su misura.</p>"),
        "/contatti": ("Contatti | Studio Lume", "<h1>Contatti</h1><p>Via Tortona 5, Milano. Su appuntamento.</p>"),
    }
    css = CSS.format(font="Cormorant Garamond", bg="#EFE8DD", ink="#2F3A2F", c1="#B08D57", c2="#7A4E2D")
    return build_site(kw, "Studio Lume Interni | Interior design a Milano",
                      "Interior design e ristrutturazioni chiavi in mano a Milano. Progetti su misura, preventivo gratuito.",
                      home, sub, css)


def build_site(kw, title, desc, home, sub, css):
    common = {k: kw[k] for k in ("lang", "site_name", "theme", "font") if k in kw}
    extra = {k: kw[k] for k in ("rtl", "hreflang", "extra_head") if k in kw}
    files = {"/": page(title=title, desc=desc, body=home, nav=kw["nav"], **common, **extra), "/style.css": css}
    for path, (t, body) in sub.items():
        files[path] = page(title=t, desc=desc, body=body, nav=kw["nav"], **common, **extra)
    return files


def competitor_site(name, lang, headline, promo=None, price="49"):
    body = f"<h1>{headline}</h1><p>{name}. {price} € · 4,7 ★</p>" + (f"<p class='promo'>{promo}</p>" if promo else "")
    return {"/": page(lang=lang, title=f"{name} | {headline}", desc=headline, body=body, nav=[("/angebote", "offers"), ("/news", "news")],
                      site_name=name, theme="#333399", font="Inter"),
            "/news": page(lang=lang, title=f"News | {name}", desc=headline, body=f"<h2>{headline} — news</h2>", nav=[],
                          site_name=name, theme="#333399", font="Inter")}


# expected truth per business — what a correct onboarding should end up with
BIZ = [
    dict(slug="spreebogen", name="Zahnarztpraxis Spreebogen", domain="spreebogen-zahnarzt.de", lang_arg="DE",
         pillars="Prophylaxe,Angstpatienten,Ästhetik,Team & Praxis,Patientenstimmen", site=site_spreebogen,
         expect=dict(primary="de", langs=["de"], currency="EUR", tz="Europe/Berlin", countries=["DE"], industry=["Clinic"],
                     restricted=True, big_price="2.900", palette="#0E7C86"),
         landing="https://spreebogen-zahnarzt.de/termin?utm_source=otto",
         meta=dict(ad_account=True, pixel=True, lead_form=True, acct_currency="EUR"), google=dict(revoked=True),
         competitor=dict(name="Zahnzentrum Alexanderplatz", lang="de", v1="Ihr Zahnarzt am Alex", v2="Neu: Bleaching-Wochen", promo="20% Rabatt auf Bleaching")),
    dict(slug="ondaviva", name="Onda Viva Surf School", domain="ondaviva-surf.com", lang_arg="PT/EN",
         pillars="Aulas,Ondas & spots,Segurança,Comunidade,Viagens de surf", site=site_ondaviva,
         expect=dict(primary="pt", langs=["pt", "en"], currency="EUR", tz="Europe/Lisbon", countries=["PT"],
                     industry=["Education", "Fitness", "Hotel", "Sport"], restricted=False, big_price="1.190", palette="#0A6E8A"),
         landing={"cold": "https://ondaviva-surf.com/en/?v=3", "hot": "https://ondaviva-surf.com/aulas-e-precos"},
         meta=dict(ad_account=True, pixel=False, lead_form=False, acct_currency="EUR"), google=dict(revoked=False),
         competitor=dict(name="Caparica Surf Lab", lang="pt", v1="Aulas de surf na Caparica", v2="Promoção de outono", promo="Black Friday -30%")),
    dict(slug="grachtenkoffie", name="Grachten Koffiebranders", domain="grachtenkoffie.nl", lang_arg="NL/EN",
         pillars="Herkomst,Brewing tips,Achter de brander,Abonnement,Reviews", site=site_grachten,
         expect=dict(primary="nl", langs=["nl", "en"], currency="EUR", tz="Europe/Amsterdam", countries=["NL"], industry=["E-commerce"],
                     restricted=False, big_price=None, palette="#C8553D"),
         meta=dict(ad_account=True, pixel=True, lead_form=False, acct_currency="USD"), google=None,
         competitor=dict(name="Bonenbar Utrecht", lang="nl", v1="Verse bonen uit Utrecht", v2="Nieuwe oogst Kenia", promo="gratis verzending")),
    dict(slug="ofek", name="מכללת אופק", domain="ofek-college.co.il", lang_arg="HE",
         pillars="סיפורי בוגרים,מהו טיפול באמנות,הסבה מקצועית,מאחורי הקלעים,שאלות ותשובות", site=site_ofek,
         expect=dict(primary="he", langs=["he"], currency="ILS", tz="Asia/Jerusalem", countries=["IL"], industry=["Education"],
                     restricted=True, big_price="18,500", palette="#6C3FB5"),
         meta=dict(ad_account=True, pixel=False, lead_form=True, acct_currency="ILS"), google=dict(revoked=False),
         competitor=dict(name="מכללת גל", lang="he", v1="לימודי טיפול באמנות", v2="מחזור חדש בנובמבר", promo="20% הנחה")),
    dict(slug="studiolume", name="Studio Lume Interni", domain="studiolume.it", lang_arg="IT",
         pillars="Progetti,Prima e dopo,Consigli luce,Materiali,Studio", site=site_lume,
         expect=dict(primary="it", langs=["it"], currency=None, tz="Europe/Rome", countries=["IT"], industry=["Home"],
                     restricted=False, big_price=None, palette="#B08D57"),
         meta=dict(ad_account=False, pixel=False, lead_form=False, acct_currency="EUR"), google=None,
         competitor=dict(name="Atelier Navigli", lang="it", v1="Interior design Navigli", v2="Nuova collezione", promo="Sale fino al 40%")),
]

# copy the agent (Quill) would write — in the brand's language; the simulation checks nothing turns it into English
COPY = {
    "spreebogen": [("Zahnreinigung ohne Stress: so läuft Ihr Termin ab", "60 Minuten, ein fester Ansprechpartner, und wir erklären jeden Schritt. Termine auch samstags."),
                   ("Angst vor dem Zahnarzt? Sie sind nicht allein", "Viele unserer Patientinnen und Patienten kommen mit einem mulmigen Gefühl. Wir planen extra Zeit ein."),
                   ("Aligner oder feste Spange – was passt zu Ihnen?", "Drei Fragen, die wir in der Beratung immer stellen. Die Antworten überraschen oft."),
                   ("Ein Tag am Spreebogen: unser Team stellt sich vor", "Fünf Zahnärztinnen und Zahnärzte, zwölf Prophylaxe-Fachkräfte und ein Praxishund."),
                   ("„Völlig schmerzfrei erklärt“ – Julia erzählt", "Warum Julia nach Jahren wieder zum Zahnarzt geht. Ihre Geschichte in drei Bildern.")],
    "ondaviva": [("A tua primeira onda em 2 horas", "Fato, prancha e instrutor incluídos. Aulas todos os dias na Costa da Caparica."),
                 ("Onde surfar em outubro perto de Lisboa", "Três praias para iniciantes, com as marés certas para esta semana."),
                 ("Segurança primeiro: como escolhemos o spot", "Os nossos instrutores são nadadores-salvadores. É assim que decidimos onde entrar."),
                 ("A comunidade Onda Viva", "Mais de 12.000 alunos desde 2012. Hoje apresentamos o Rui e os filhos."),
                 ("Surf camp: uma semana que muda o verão", "Sete dias, duas aulas por dia e vídeo-análise no fim de cada sessão.")],
    "grachtenkoffie": [("Waar komt je Guji eigenlijk vandaan?", "Van de hellingen van Guji naar onze brander aan de Keizersgracht, in zes weken."),
                       ("Filterkoffie zetten in 4 stappen", "Maalgraad, water, tijd en geduld. Zo haal je bosbes uit je Guji."),
                       ("Dinsdag is branddag", "Kijk mee achter de brander: kleine batches, elke dinsdag en vrijdag."),
                       ("Nooit meer zonder bonen", "Het abonnement: elke twee weken verse koffie in de brievenbus, opzeggen wanneer je wilt."),
                       ("\"Ruikt echt naar bosbessen\" – Sanne", "Wat klanten zeggen over de Ethiopia Guji. Nu weer op voorraad.")],
    "ofek": [("בגיל 41 היא התחילה מחדש", "מיכל עזבה את ההייטק ופתחה קליניקה משלה. הסיפור שלה בשלוש תמונות."),
             ("מה זה בעצם טיפול באמנות?", "שלושה דברים שכדאי לדעת לפני שבוחרים מסלול לימודים טיפולי."),
             ("הסבה מקצועית בלי לעצור את החיים", "לימודים פעמיים בשבוע, בתל אביב ובזום. כך זה נראה בפועל."),
             ("יום לימודים באופק", "מאחורי הקלעים של סדנת חומרים עם הסטודנטים של מחזור אוקטובר."),
             ("שאלתם, ענינו: כמה זמן לוקח להסמכה?", "כל התשובות על מסלול התעודה, ההדרכה הקלינית והפרקטיקום.")],
    "studiolume": [("Un bilocale buio, trasformato", "Porta Romana, 48 metri quadri: come abbiamo portato la luce in ogni stanza."),
                   ("Prima e dopo: la cucina in Isola", "Tre scelte di materiali che hanno cambiato tutto."),
                   ("Luce naturale: 3 errori da evitare", "Tende, specchi e colori: i consigli che diamo in ogni sopralluogo."),
                   ("Rovere, ottone, terrazzo", "I materiali che usiamo di più quest'autunno e perché."),
                   ("Dentro lo studio", "Come nasce un progetto: dal sopralluogo al cronoprogramma condiviso.")],
}
# compliance violations the pipeline must catch (restricted brands) — injected into the first week
VIOLATION = {"spreebogen": ("Wir heilen Parodontitis – garantiert in einer Sitzung", "Parodontitis wird bei uns geheilt. Termin jetzt buchen."),
             "ofek": ("האם אתה סובל מחרדה? בוא ללמוד טיפול באמנות", "הקורס שלנו מרפא חרדה ומשנה חיים.")}
LANG_MARKERS = {"en": re.compile(r"\b(the|and|your|with|link in bio|learn more|talk to us|official site)\b", re.I)}

# ============================================================================================
# results
# ============================================================================================

STEPS = ["scan", "onboard", "strategy", "competitors", "plan-dry", "plan", "copy", "visuals", "compliance", "tg-dry", "tg-cards",
         "approvals", "publish-dry", "publish", "ads-plan", "ads-launch", "insights", "insights-daily", "ads-report", "watch", "growth",
         "demo", "reels"]
ORDER = {"PASS": 0, "SKIP": 1, "WARN": 2, "FAIL": 3}


class StepFail(Exception):
    pass


class Results:
    def __init__(self):
        self.cells = {}
        self.timings = {}
        self.cur = None

    def _cell(self, row, step):
        return self.cells.setdefault((row, step), {"status": "PASS", "notes": [], "secs": 0.0})

    @contextlib.contextmanager
    def step(self, row, step):
        c = self._cell(row, step)
        prev, self.cur = self.cur, (row, step)
        t0 = time.time()
        try:
            yield c
        except StepFail as e:
            self.mark("FAIL", str(e))
        except SystemExit as e:
            self.mark("FAIL", f"SystemExit: {e.code}")
        except Exception as e:
            self.mark("FAIL", f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=6))
        finally:
            c["secs"] += time.time() - t0
            self.cur = prev

    def mark(self, level, note, row_step=None):
        c = self._cell(*(row_step or self.cur))
        if ORDER[level] > ORDER[c["status"]]:
            c["status"] = level
        c["notes"].append(f"[{level}] {note}")

    def warn(self, note):
        self.mark("WARN", note)

    def fail(self, note):
        self.mark("FAIL", note)

    def skip(self, note):
        self.mark("SKIP", note)

    def check(self, cond, note, level="FAIL"):
        if not cond:
            self.mark(level, note)
        return bool(cond)

    def rows(self):
        seen = []
        for r, _ in self.cells:
            if r not in seen:
                seen.append(r)
        return seen


R = Results()

# ============================================================================================
# workspace, network guard, fakes, clock
# ============================================================================================

GUARD = '''
import socket as _s
_LOCAL = ("127.0.0.1", "::1", "localhost")
_ga, _conn = _s.getaddrinfo, _s.socket.connect
def _getaddrinfo(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else str(host)
    if h not in _LOCAL and not h.startswith("127."):
        raise _s.gaierror(-2, "offline simulation: no DNS for " + h)
    return _ga(host, *a, **k)
def _connect(self, addr):
    h = addr[0] if isinstance(addr, tuple) else addr
    if isinstance(h, str) and h not in _LOCAL and not h.startswith("127.") and not h.startswith("/"):
        raise OSError("offline simulation: connection to %s refused" % (h,))
    return _conn(self, addr)
_s.getaddrinfo = _getaddrinfo
_s.socket.connect = _connect
# the simulated clock in CLI subprocesses (otto_plan.py build, ap.py …): OTTO_SIM_CLOCK, set by cli() from FakeClock. Without
# it a subprocess plans against the real date, and once the real date reaches the simulated month the results drift.
import os as _os
_clk = _os.environ.get("OTTO_SIM_CLOCK")
if _clk:
    import datetime as _dtm
    _RD, _RDate = _dtm.datetime, _dtm.date
    _NOW = _RD.fromisoformat(_clk.replace("Z", "+00:00")).astimezone(_dtm.timezone.utc)
    class _SimDT(_RD):
        @classmethod
        def now(cls, tz=None):
            return _NOW.astimezone(tz) if tz else _NOW.replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return _NOW.replace(tzinfo=None)
    class _SimDate(_RDate):
        @classmethod
        def today(cls):
            return _NOW.date()
    _dtm.datetime, _dtm.date = _SimDT, _SimDate
'''


class WS:
    """The isolated workspace (paths + env)."""

    def __init__(self, root):
        self.root = Path(root)
        self.env = {"OTTO_DATA": str(self.root / "data.json"), "OTTO_HTML": str(self.root / "index.html"),
                    "OTTO_SECRETS": str(self.root / "secrets"), "OTTO_BRANDS": str(self.root / "brands"),
                    "OTTO_ASSETS": str(self.root / "assets"), "OTTO_PUBLIC_ASSETS": str(self.root / "public"),
                    "OTTO_MOTION_ROOT": str(self.root / "motion"), "OTTO_TEXT_SHAPING": "0",
                    "PYTHONPATH": str(self.root / "guard"), "PYTHONDONTWRITEBYTECODE": "1"}

    def build(self):
        html = (PLATFORM / "index.html").read_text()
        data = json.loads((Path(__file__).resolve().parent / "fixtures" / "data.json").read_text())   # never the page's block:
        (self.root / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))   # the two pilot brands stay in
        (self.root / "index.html").write_text(html)                                             # it is neutral when committed
        shutil.copytree(REPO / "brands", self.root / "brands")
        shutil.copytree(PLATFORM / "assets" / "posts", self.root / "assets" / "posts")
        for d in ("secrets", "public", "motion", "guard", "demo", "calls"):
            (self.root / d).mkdir(exist_ok=True)
        (self.root / "guard" / "sitecustomize.py").write_text(GUARD)
        (self.root / "secrets" / "telegram.json").write_text(json.dumps({"bot_token": "000:FAKE", "owner_chat_id": "42"}))
        for b in BIZ:
            m = b["meta"]
            c = {"access_token": f"EAAB-fake-{b['slug']}", "page_id": f"PG{b['slug']}", "ig_user_id": f"IG{b['slug']}"}
            if m["ad_account"]:
                c["ad_account_id"] = f"act_{b['slug']}"
            if m["pixel"]:
                c["pixel_id"] = f"PX{b['slug']}"
            if m["lead_form"]:
                c["lead_form_id"] = f"LF{b['slug']}"
            (self.root / "secrets" / f"meta-{b['slug']}.json").write_text(json.dumps(c))
            if b["google"] is not None:
                g = {"client_id": "cid", "client_secret": "csec", "developer_token": "dev", "customer_id": "123-456-7890",
                     "refresh_token": ("revoked-" if b["google"]["revoked"] else "ok-") + b["slug"]}
                (self.root / "secrets" / f"google-{b['slug']}.json").write_text(json.dumps(g))
        return self


def install_guard():
    exec(compile(GUARD, "<sim-guard>", "exec"), {})


class FakeClock:
    """Replaces datetime/date in the engine modules so time can move forward."""
    now = None

    @classmethod
    def set(cls, iso):
        cls.now = _real_datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


class SimDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if FakeClock.now is None:
            return _real_datetime.now(tz)
        return FakeClock.now.astimezone(tz) if tz else FakeClock.now.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return cls.now(timezone.utc).replace(tzinfo=None)


class SimDate(_real_date):
    @classmethod
    def today(cls):
        return (FakeClock.now or _real_datetime.now(timezone.utc)).date()


def install_clock(mods):
    for m in mods:
        if hasattr(m, "datetime") and m.datetime is _real_datetime:
            m.datetime = SimDatetime
        if hasattr(m, "date") and m.date is _real_date:
            m.date = SimDate


PID_RE = re.compile(r"/(?:posts|reels|ads)/([a-z]{2,4}-\d{3,})(?:-c?\d+)?(?:-static)?\.(?:jpe?g|png|mp4)")


class FakeMeta:
    """Graph API stand-in: publishing, ads objects, insights. Records every call; injectable failures per post id."""

    def __init__(self, log_file=None, delay=0.0):
        self.calls, self.seq, self.inject = [], 1000, {}
        self.containers, self.photos, self.published = {}, {}, []
        self.acct_currency, self.ads_rows, self.post_metrics = {}, {}, {}
        self.log_file, self.delay = log_file, delay

    def _id(self):
        self.seq += 1
        return str(self.seq) + ("" if not self.log_file else "-" + str(os.getpid()))

    def _pid(self, params):
        for k in ("children",):
            for cid in (params.get(k) or "").split(","):
                if cid in self.containers:
                    return self.containers[cid]
        for v in params.values():
            if isinstance(v, str):
                m = PID_RE.search(v)
                if m:
                    return m.group(1)
                if v in self.containers:
                    return self.containers[v]
                if v in self.photos:
                    return self.photos[v]
        am = params.get("attached_media")
        if am:
            for x in json.loads(am):
                if x.get("media_fbid") in self.photos:
                    return self.photos[x["media_fbid"]]
        return None

    def graph(self, method, path, token, **params):
        import otto_publish as pub
        pid = self._pid(params)
        final = method == "POST" and (path.endswith("/media_publish") or path.endswith("/feed") or path.endswith("/videos")
                                      or path.endswith("/photo_stories") or (path.endswith("/photos") and "message" in params))
        rec = {"m": method, "path": path, "pid": pid, "final": final, "keys": sorted(params)}
        self.calls.append(rec)
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(dict(rec, proc=os.getpid())) + "\n")
        if self.delay:
            time.sleep(self.delay)
        mode = self.inject.get(pid)
        if mode == "graph_error_once" and method == "POST":
            self.inject.pop(pid)
            raise pub.GraphError("Graph 100: (#100) Invalid parameter (simulated)")
        if mode == "graph_error" and method == "POST":
            raise pub.GraphError("Graph 100: (#100) Invalid parameter (simulated)")
        if mode == "timeout" and final:
            raise urllib.error.URLError("timed out (simulated)")
        # ---- organic publishing
        if method == "POST" and path.endswith("/photos"):
            i = self._id()
            if params.get("published") == "false":
                self.photos[i] = pid
                return {"id": i}
            self.published.append((pid, path))
            return {"id": i, "post_id": f"{path.split('/')[0]}_{i}"}
        if method == "POST" and path.endswith("/media") and not path.startswith("act_"):
            i = "C" + self._id()
            self.containers[i] = pid
            return {"id": i}
        if method == "GET" and params.get("fields") == "status_code":
            return {"status_code": "FINISHED"}
        if final:
            self.published.append((pid or self.containers.get(params.get("creation_id")), path))
            return {"id": self._id(), "post_id": self._id()}
        # ---- ads
        if method == "GET" and path.startswith("act_") and "/" not in path:
            return {"currency": self.acct_currency.get(path, "EUR")}
        if method == "GET" and path.startswith("act_") and path.endswith("/insights"):
            return {"data": self.ads_rows.get(path.split("/")[0], lambda preset: [])(params.get("date_preset"))}
        if method == "POST" and path.endswith("/adimages"):
            return {"images": {params.get("name", "x"): {"hash": "h" + self._id()}}}
        if method == "POST" and path.split("/")[-1] in ("campaigns", "adsets", "adcreatives", "ads", "advideos"):
            return {"id": path.split("/")[-1][:3].upper() + self._id()}
        if method == "GET" and params.get("fields") == "status":
            return {"status": {"video_status": "ready"}}
        if method == "POST" and "status" in params:
            return {"success": True}
        # ---- insights
        if method == "GET" and path.endswith("/insights"):
            obj = path.rsplit("/", 1)[0]
            vals = self.post_metrics.get(obj) or {}
            names = params.get("metric", "").split(",")
            retired = [n for n in names if n.startswith(("page_impressions", "page_fans", "post_impressions")) or n == "impressions"]
            if retired:                                  # what Meta answers since 15.11.2025 (otto_metrics drops them)
                raise pub.GraphError("Graph 100: (#100) The value must be a valid insights metric", code=100)
            return {"data": [{"name": n, "values": [{"value": vals.get(n, 1200 if n.startswith("page_") else 0)}]} for n in names if n]}
        if method == "GET" and "followers_count" in params.get("fields", ""):
            return {"followers_count": 1500, "fan_count": 1400}
        if method == "GET" and "shares" in params.get("fields", ""):
            v = self.post_metrics.get(path) or {}
            return {"shares": {"count": v.get("shares", 1)}, "comments": {"summary": {"total_count": v.get("comments", 2)}},
                    "reactions": {"summary": {"total_count": v.get("likes", 9)}}}
        return {"id": self._id()}


class FakeTelegram:
    def __init__(self, log_file=None, delay=0.0):
        self.calls, self.mid, self.log_file, self.delay = [], 500, log_file, delay

    def api(self, method, files=None, **kw):
        self.calls.append((method, kw, bool(files)))
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(json.dumps({"m": method, "text": str(kw.get("caption") or kw.get("text") or "")[:300], "proc": os.getpid()}) + "\n")
        if self.delay:
            time.sleep(self.delay)
        if method in ("sendMessage", "sendPhoto"):
            self.mid += 1
            return {"message_id": self.mid}
        return True


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeGoogle:
    """urllib.request.urlopen replacement: Google OAuth + Ads REST; every other URL is refused (offline)."""

    def __init__(self):
        self.calls = []

    def urlopen(self, req, *a, **kw):
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        host = urllib.parse.urlsplit(url).hostname or ""
        self.calls.append(url)
        if host == "oauth2.googleapis.com":
            body = urllib.parse.parse_qs((req.data or b"").decode())
            if body.get("refresh_token", [""])[0].startswith("revoked-"):
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(
                    b'{"error": "invalid_grant", "error_description": "Token has been expired or revoked."}'))
            return _Resp(json.dumps({"access_token": "ya29.fake", "expires_in": 3599}).encode())
        if host == "googleads.googleapis.com":
            if url.endswith("googleAds:searchStream"):
                return _Resp(b"[]")
            if url.endswith("googleAds:mutate"):
                ops = json.loads(req.data.decode())["mutateOperations"]
                return _Resp(json.dumps({"mutateOperationResponses": [
                    {"campaignResult": {"resourceName": "customers/1234567890/campaigns/9001"}} if "campaignOperation" in o else {"x": {}}
                    for o in ops]}).encode())
            return _Resp(b"{}")
        if host in ("127.0.0.1", "localhost"):
            return _real_urlopen(req, *a, **kw)
        raise urllib.error.URLError(f"offline simulation: {host} blocked")


_real_urlopen = urllib.request.urlopen


class Site(http.server.BaseHTTPRequestHandler):
    files, special = {}, {}

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in self.special:
            code, headers, body = self.special[path]
        elif path in self.files:
            body = self.files[path]
            body = body.encode() if isinstance(body, str) else body
            code, headers = 200, {"Content-Type": "text/css" if path.endswith(".css") else "text/html; charset=utf-8"}
        else:
            code, headers, body = 404, {"Content-Type": "text/html"}, b"<h1>404</h1>"
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(files, special=None):
    handler = type("SiteH", (Site,), {"files": dict(files), "special": dict(special or {})})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", handler


# ============================================================================================
# helpers
# ============================================================================================

WSP = None
M = {}          # loaded engine modules
META, TG, GOOG = FakeMeta(), FakeTelegram(), FakeGoogle()
SENT = []       # otto_watch / notify messages
IDS = {}        # slug -> {"posts": [...], ...}


def cli(*args, timeout=180, env=None):
    e = dict(os.environ, **WSP.env)
    if FakeClock.now is not None:                           # the subprocess lives on the simulated clock too (GUARD)
        e["OTTO_SIM_CLOCK"] = FakeClock.now.isoformat()
    e.update(env or {})
    t0 = time.time()
    r = subprocess.run([sys.executable] + [str(a) for a in args], cwd=str(PLATFORM), env=e, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr, time.time() - t0


def call(fn, *a, **kw):
    """Run an engine function in-process; returns (result, output, exit_code)."""
    buf = io.StringIO()
    code, ret = 0, None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            ret = fn(*a, **kw)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int) and e.code is not None:
                buf.write(str(e.code))
    return ret, buf.getvalue(), code


def data():
    return M["ap"].load()


def posts_of(slug, d=None):
    return [p for p in (d or data())["posts"] if p["brand"] == slug]


def ffmpeg():
    return shutil.which("ffmpeg")


def load_engine():
    sys.path.insert(0, str(PLATFORM))
    for k, v in WSP.env.items():
        os.environ[k] = v
    import ap, otto_paths, otto_scan, otto_strategy, otto_competitors, otto_plan, otto_creative, otto_compliance, otto_telegram
    import otto_publish, otto_ads, otto_insights, otto_watch, otto_growth, otto_demo, otto_motion, otto_video, genvisuals, otto_api
    import otto_i18n, otto_report, otto_email
    for m in (ap, otto_paths, otto_scan, otto_strategy, otto_competitors, otto_plan, otto_creative, otto_compliance, otto_telegram,
              otto_publish, otto_ads, otto_insights, otto_watch, otto_growth, otto_demo, otto_motion, otto_video, genvisuals, otto_api,
              otto_i18n, otto_report, otto_email):
        M[m.__name__] = m
    install_clock([ap, otto_publish, otto_telegram, otto_watch, otto_insights, otto_ads, otto_growth, otto_competitors, otto_scan,
                   otto_report])
    # fakes: Meta Graph, Telegram, OpenClaw sender, Google (urlopen)
    otto_publish.graph = META.graph
    otto_telegram.api = TG.api
    otto_watch.send = lambda text: SENT.append(("watch", text)) or True
    urllib.request.urlopen = GOOG.urlopen
    # relax the scanner's public-IP guard for the fixture host ONLY (private redirects stay blocked)
    orig_ok = otto_scan.ip_ok
    otto_scan.ip_ok = lambda ip: str(ip) == "127.0.0.1" or orig_ok(ip)


ISOLATION_ATTRS = [("ap", "DATA"), ("ap", "HTML"), ("ap", "BRANDS"), ("otto_paths", "ASSETS"), ("otto_scan", "BRANDS"),
                   ("otto_strategy", "BRANDS"), ("otto_competitors", "BRANDS"), ("otto_plan", "BRANDS"), ("otto_creative", "BRANDS"),
                   ("otto_creative", "OUT"), ("genvisuals", "OUT"), ("otto_ads", "BRANDS"), ("otto_ads", "SECRETS"),
                   ("otto_insights", "BRANDS"), ("otto_publish", "SECRETS"), ("otto_publish", "LOG"), ("otto_telegram", "SECRETS"),
                   ("otto_telegram", "STATE"), ("otto_watch", "HIST"), ("otto_watch", "STATE"), ("otto_growth", "HIST"),
                   ("otto_video", "REELS"), ("otto_video", "SECRETS"), ("otto_demo", "BRANDS"), ("otto_motion", "BRANDS"),
                   ("otto_motion", "REELS"), ("otto_motion", "MOTION"), ("otto_api", "LOG")]
UNSAFE_CLI = set()


def isolation_preflight():
    """Every path an engine module writes/reads must be inside the workspace. A module that ignores the OTTO_* env is a
    FAIL (it would touch the real repo) — it is re-pointed in-process so the run stays safe, and never run as a subprocess."""
    root = WSP.root.resolve()
    with R.step("ENGINE", "isolation"):
        for mod, attr in ISOLATION_ATTRS:
            m = M[mod]
            p = getattr(m, attr, None)
            if p is None:
                continue
            p = Path(p).resolve()
            try:
                p.relative_to(root)
            except ValueError:
                rel = p.relative_to(PLATFORM.resolve()) if str(p).startswith(str(PLATFORM.resolve())) else p.relative_to(REPO.resolve())
                R.fail(f"{mod}.{attr} = {p} ignores the OTTO_* environment — would touch the real repo")
                UNSAFE_CLI.add(mod)
                target = {"BRANDS": root / "brands", "REELS": root / "assets" / "reels", "MOTION": root / "motion"}.get(attr, root / rel.name)
                setattr(m, attr, target)
        demo_src = Path(M["otto_demo"].__file__).read_text()
        if 'HERE / "data.json"' in demo_src:
            R.fail("otto_demo reads HERE/data.json (and index.html) directly — ignores OTTO_DATA")
            UNSAFE_CLI.add("otto_demo")


# ============================================================================================
# lifecycle steps
# ============================================================================================

SERVERS = {}


def step_scan(b):
    sc = M["otto_scan"]
    with R.step(b["slug"], "scan"):
        srv, url, _ = serve(b["site"]())
        sc.ALLOWED_PORTS = sc.ALLOWED_PORTS | {srv.server_address[1]}
        SERVERS[b["slug"]] = (srv, url)
        _, out, code = call(sc.run_cli, [url + "/", "--slug", b["slug"]])
        R.check(code == 0, f"otto_scan exited {code}: {out[-300:]}")
        sj = WSP.root / "brands" / b["slug"] / "scan.json"
        if not R.check(sj.exists(), "scan.json not written"):
            return
        s = json.loads(sj.read_text())
        e = b["expect"]
        R.check(s["languages"][:1] == [e["primary"]], f"primary language {s['languages']} (expected {e['primary']})", "WARN")
        missing = [l for l in e["langs"] if l not in s["languages"]]
        R.check(not missing, f"languages missing {missing} (got {s['languages']})", "WARN")
        R.check(s["commerce"]["currency"] == e["currency"], f"currency {s['commerce']['currency']} (expected {e['currency']})", "WARN")
        if e["big_price"]:
            R.check(any(e["big_price"] in p for p in s["commerce"]["prices"]),
                    f"price ≥1,000 mis-parsed: expected '{e['big_price']}' in {s['commerce']['prices']}", "WARN")
        pal = [x["hex"] for x in s["visual"]["palette"]]
        R.check(e["palette"] in pal, f"brand colour {e['palette']} not in palette {pal}", "WARN")
        R.check(bool(s["visual"]["logo"]), "no logo found", "WARN")
        R.check(len(s["pages"]) >= 3, f"only {len(s['pages'])} page(s) read — localized subpage slugs not followed: {s['pages']}", "WARN")
        R.check(any(k.lower() in s["industry"].lower() for k in e["industry"]), f"industry guess '{s['industry']}' (expected {e['industry']})", "WARN")
        R.check((WSP.root / "brands" / b["slug"] / "brand-profile.md").exists(), "brand-profile.md draft not written")
        cur = M["ap"].brand_currency(data(), b["slug"])
        R.check(cur == (e["currency"] or "EUR"), f"brand currency resolves to {cur} (expected {e['currency'] or 'EUR'})", "WARN")
        R.mark("PASS", f"{len(s['pages'])} pages · langs {s['languages']} · {s['industry']} · {s['commerce']['currency']} · "
                       f"prices {s['commerce']['prices'][:4]} · palette {pal[:3]}")


def step_onboard(b):
    with R.step(b["slug"], "onboard"):
        code, out, _ = cli("ap.py", "brand-add", b["slug"], b["name"], b["domain"], b["lang_arg"], b["pillars"],
                           "--approvals", "telegram")    # the simulated owners approve in Telegram (new brands default to e-mail)
        R.check(code == 0, f"brand-add failed: {out[-300:]}")
        br = M["ap"].brand(data(), b["slug"])
        if not R.check(br is not None, "brand not in data.json"):
            return
        e = b["expect"]
        R.check(br.get("tz") == e["tz"], f"brands[].tz = {br.get('tz')} (business is in {e['tz']}) — slots run on the wrong clock", "WARN")
        lang = M["ap"].brand_lang(br)
        R.check(lang == e["primary"], f"brand_lang = {lang} (expected {e['primary']})")
        code, out, _ = cli("ap.py", "brand-add", b["slug"], b["name"], b["domain"], b["lang_arg"])
        R.check(code != 0 and "exists" in out, "second brand-add with the same slug was not refused")
        with M["ap"].transaction(sync=False) as dd:  # a paying Growth client (a linked subscription), so the engine runs —
            bb = M["ap"].brand(dd, b["slug"])        # Starter/Content limits are covered by tests/test_plans.py
            bb["plan"] = "growth"; bb.pop("plan_billing", None)
            if b.get("landing"):                  # what the onboarding agent records after the owner's answers
                bb["landing"] = b["landing"]
        R.mark("PASS", f"tz {br.get('tz')} · lang {lang} · countries {br.get('countries')}")


def step_strategy(b):
    st = M["otto_strategy"]
    with R.step(b["slug"], "strategy"):
        if "otto_strategy" in UNSAFE_CLI:
            _, out, code = call(st.init, b["slug"])
            _, out2, code2 = call(st.check, b["slug"])
            _, out3, code3 = call(st.concepts, b["slug"], 3)
        else:
            code, out, _ = cli("otto_strategy.py", "init", b["slug"])
            code2, out2, _ = cli("otto_strategy.py", "check", b["slug"])
            code3, out3, _ = cli("otto_strategy.py", "concepts", b["slug"], "3")
        R.check(code == 0 and code2 == 0 and code3 == 0, f"strategy exit codes {code}/{code2}/{code3}: {(out + out2 + out3)[-400:]}")
        f = WSP.root / "brands" / b["slug"] / "strategy.json"
        if not R.check(f.exists(), "strategy.json not written in the workspace"):
            return
        s = json.loads(f.read_text())
        e = b["expect"]
        br = M["ap"].brand(data(), b["slug"]) or {}
        R.check(s["language"] == e["primary"], f"strategy language {s['language']} (expected {e['primary']})", "WARN")
        R.check(s["currency"] == (e["currency"] or "EUR"), f"strategy currency {s['currency']} (expected {e['currency'] or 'EUR'})", "WARN")
        R.check(s["tz"] == e["tz"], f"strategy tz {s['tz']} (business in {e['tz']}; brands[].tz {br.get('tz')})", "WARN")
        R.check(len(s["ask"]) <= 4, f"{len(s['ask'])} onboarding questions (max 4)")
        R.check(len(s["proof_bank"]) >= 1, "empty proof bank (the site has reviews + trust lines)", "WARN")
        R.check("?" in out2, "check printed no onboarding questions", "WARN")
        R.mark("PASS", f"{len(s['personas'])} personas · {len(s['proof_bank'])} proof · {len(s['offers'])} offers · ask {len(s['ask'])}")


def step_competitors(b):
    co = M["otto_competitors"]
    c = b["competitor"]
    with R.step(b["slug"], "competitors"):
        v1 = competitor_site(c["name"], c["lang"], c["v1"])
        srv, url, handler = serve(v1)
        M["otto_scan"].ALLOWED_PORTS = M["otto_scan"].ALLOWED_PORTS | {srv.server_address[1]}
        code, out, _ = cli("otto_competitors.py", "add", b["slug"], c["name"], url + "/", "--type", "direct")
        R.check(code == 0, f"competitors add failed: {out[-200:]}")
        code, out, _ = cli("otto_competitors.py", "add", b["slug"], "Unknown Rival " + b["slug"].title())   # no site → offline lookup
        rec_before = len([r for r in data()["recommendations"] if r.get("brand") == b["slug"]])
        _, out, code = call(co.sweep, b["slug"], None, True)
        R.check(code == 0, f"sweep --dry exited {code}: {out[-300:]}")
        m = re.search(r"country (\w+)", out)
        country = m.group(1) if m else "?"
        R.check(country == b["expect"]["countries"][0], f"sweep country {country} (business sells in {b['expect']['countries'][0]}) — "
                                                          "Ad Library / Transparency links point at the wrong market", "WARN")
        R.check(not (WSP.root / "brands" / b["slug"] / "competitor-research.md").exists(), "--dry wrote competitor-research.md")
        _, out, code = call(co.sweep, b["slug"], None, False)
        R.check(code == 0, f"sweep exited {code}")
        handler.files.update(competitor_site(c["name"], c["lang"], c["v2"], promo=c["promo"], price="59"))
        _, out2, code = call(co.sweep, b["slug"], None, False)
        R.check("change" in out2 and not re.search(r"-- 0 changes", out2), f"second sweep saw no change after the competitor site changed: {out2[-300:]}", "WARN")
        _, out3, _ = call(co.sweep, b["slug"], None, False)
        recs = [r for r in data()["recommendations"] if r.get("brand") == b["slug"] and r.get("source") == "otto_competitors"]
        R.check(len(recs) <= 1, f"{len(recs)} competitor recommendations after 3 sweeps (dedupe)")
        _, out4, _ = call(co.angles, b["slug"])
        R.mark("PASS", f"country {country} · recs {len(recs)} · {out2.strip().splitlines()[-1] if out2.strip() else ''}")
        srv.shutdown()


def local_hour(slot, tzname):
    return _real_datetime.fromisoformat(slot).replace(tzinfo=ZoneInfo(tzname)).hour


def step_plan(b, ym):
    ap = M["ap"]
    with R.step(b["slug"], "plan-dry"):
        code, out, secs = cli("otto_plan.py", "build", b["slug"], ym, "--dry")
        R.check(code == 0, f"plan --dry exited {code}: {out[-300:]}")
        R.check(not [p for p in posts_of(b["slug"]) if p.get("plan") == ym], "--dry created posts")
        m = re.search(r"-- (\d+) posts", out)
        R.mark("PASS", f"{m.group(1) if m else '?'} slots in {secs:.2f}s")
    with R.step(b["slug"], "plan"):
        code, out, secs = cli("otto_plan.py", "build", b["slug"], ym)
        R.timings[f"plan build {b['slug']} {ym}"] = secs
        R.check(code == 0, f"plan build exited {code}: {out[-300:]}")
        ps = [p for p in posts_of(b["slug"]) if p.get("plan") == ym]
        R.check(40 <= len(ps) <= 80, f"{len(ps)} posts planned for {ym}")
        br = ap.brand(data(), b["slug"])
        real_tz = b["expect"]["tz"]
        bad_hour, off = [], []
        for p in ps:
            dt = ap.slot_dt(p, br)
            loc = dt.astimezone(ZoneInfo(real_tz))
            if not (7 <= loc.hour <= 21):
                bad_hour.append(f"{p['id']} {loc:%d.%m %H:%M}")
            if loc.strftime("%H:%M") != p["slot"][11:16]:
                off.append(p["id"])
            R.check(p["slot"][:7] == ym, f"{p['id']} slot {p['slot']} outside {ym}")
        R.check(not bad_hour, f"{len(bad_hour)} post(s) go out at night local time: {bad_hour[:4]}", "WARN")
        R.check(not off, f"{len(off)} post(s) publish at a different local hour than planned ({real_tz} vs brands[].tz {br.get('tz')})", "WARN")
        fm = {}
        for p in ps:
            fm[p.get("format")] = fm.get(p.get("format"), 0) + 1
        R.check(fm.get("reel", 0) >= 4, f"only {fm.get('reel', 0)} reels (package promises 4)")
        dup = len(ps) - len({(p["slot"], p["platform"]) for p in ps})
        R.check(dup == 0, f"{dup} duplicate slot+platform pairs")
        # DST: Oct 25 2026 — local 09:00 must stay 09:00 on both sides of the change
        if ym == "2026-10":
            before = [p for p in ps if p["slot"].startswith("2026-10-23T09")]
            after = [p for p in ps if p["slot"].startswith("2026-10-26T09")]
            if before and after:
                o1, o2 = ap.slot_dt(before[0], br).utcoffset(), ap.slot_dt(after[0], br).utcoffset()
                R.check(o1 != o2 or br.get("tz") in ("UTC",), f"no DST change across Oct 25 for tz {br.get('tz')}", "WARN")
        R.check((WSP.root / "brands" / b["slug"] / f"content-plan-{ym}.md").exists(), "content-plan md missing")
        code2, out2, _ = cli("otto_plan.py", "build", b["slug"], ym)
        R.check(code2 != 0 and "already" in out2, "re-running build for the same month was not refused (cron idempotency)")
        IDS.setdefault(b["slug"], {})["plan"] = [p["id"] for p in sorted(ps, key=lambda x: x["slot"])]
        R.mark("PASS", f"{len(ps)} posts {fm} in {secs:.2f}s")


def make_images(b):
    """Stand-ins for Leonardo output: one brand-palette JPEG per post (copied), carousel slides rendered with the real
    overlay code, one short reel mp4 per brand via otto_video.demo (ffmpeg only, no voice)."""
    ap, paths, cre = M["ap"], M["otto_paths"], M["otto_creative"]
    s = json.loads((WSP.root / "brands" / b["slug"] / "scan.json").read_text())
    color = (s["visual"]["palette"] or [{"hex": "#2447F0"}])[0]["hex"]
    base = paths.ASSETS / "posts" / f"_{b['slug']}-base.jpg"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1350:d=1", "-frames:v", "1",
                    "-q:v", "3", str(base)], check=True)
    return base


def step_copy_and_visuals(b, ym):
    ap, paths, cre = M["ap"], M["otto_paths"], M["otto_creative"]
    slug = b["slug"]
    ids = IDS[slug]["plan"]
    d = data()
    with R.step(slug, "copy"):
        items = []
        texts = COPY[slug]
        for i, pid in enumerate(ids):
            h, c = texts[i % len(texts)]
            items.append({"id": pid, "hook": h, "caption": f"{h}\n\n{c}", "hashtags": [slug, "otto"], "visual_brief": f"{h} — on-brand"})
        if slug in VIOLATION:                      # a violating post inside the first card window
            vi = next(i for i, pid in enumerate(ids) if ap.post(d, pid)["slot"].startswith("2026-10-02"))
            h, c = VIOLATION[slug]
            items[vi].update({"hook": h, "caption": f"{h}\n\n{c}"})
            IDS[slug]["violator"] = ids[vi]
        f = WSP.root / f"copy-{slug}.json"
        f.write_text(json.dumps(items, ensure_ascii=False))
        code, out, _ = cli("otto_plan.py", "fill", slug, ym, str(f), "--pending")
        R.check(code == 0, f"fill failed: {out[-300:]}")
        ps = [p for p in posts_of(slug) if p.get("plan") == ym]
        R.check(all(p["status"] == "pending_approval" for p in ps), "fill --pending left posts in draft")
        R.mark("PASS", f"{len(items)} captions filled in {b['expect']['primary']} → pending_approval")
    with R.step(slug, "visuals"):
        code, out, _ = cli("genvisuals.py", "--brand", slug, "--limit", "3", "--dry")
        R.check(code == 0, f"genvisuals --dry exited {code}: {out[-300:]}")
        R.check("WOULD FIRE" in out, "genvisuals --dry fired nothing")
        s = json.loads((WSP.root / "brands" / slug / "scan.json").read_text())
        pal = [x["hex"] for x in s["visual"]["palette"]][:1]
        R.check(all(h in out for h in pal), f"genvisuals prompt misses the brand palette {pal}", "WARN")
        if not ffmpeg():
            R.skip("ffmpeg missing — images not rendered")
            return
        base = make_images(b)
        d = data()
        patches, carousels = {}, 0
        for pid in ids:
            p = ap.post(d, pid)
            dst = paths.ASSETS / "posts" / f"{pid}.jpg"
            shutil.copyfile(base, dst)
            patch = {"image": f"assets/posts/{pid}.jpg"}
            if p.get("format") == "carousel" and carousels < 2:        # real overlay code for two carousels per brand
                slides = []
                for j, txt in enumerate([p["hook"], COPY[slug][1][1][:60], cre.cta_card_text(ap.brand(d, slug))], 1):
                    sd = paths.ASSETS / "posts" / f"{pid}-{j}.jpg"
                    cre.overlay_text(dst, sd, txt, pal[0] if pal else "#2447F0", pos="bottom" if j > 1 else "center", size=58)
                    slides.append(f"assets/posts/{sd.name}")
                patch["images"] = slides
                carousels += 1
                R.check(paths.sniff(WSP.root / "assets" / "posts" / f"{pid}-1.jpg") == "jpeg", "carousel slide is not JPEG")
            elif p.get("format") == "carousel":
                patch["images"] = [f"assets/posts/{pid}.jpg", f"assets/posts/{pid}.jpg"]
            patches[pid] = patch
        # one IG feed post left WITHOUT an image on purpose (studiolume) → the publisher must refuse it, not crash
        if slug == "studiolume":
            ig = next(pid for pid in ids if ap.post(d, pid)["platform"] == "ig" and ap.post(d, pid).get("format") == "post")
            patches.pop(ig, None)
            IDS[slug]["no_image"] = ig
        with ap.transaction(sync=False) as dd:
            for pid, patch in patches.items():
                ap.post(dd, pid).update(patch)
        # reel: the real ffmpeg reel assembly (otto_video.demo, no voice) once per brand
        reel = paths.ASSETS / "reels" / f"_{slug}-demo.mp4"
        reel.parent.mkdir(parents=True, exist_ok=True)
        (WSP.root / "tmp").mkdir(exist_ok=True)
        tempfile.tempdir = str(WSP.root / "tmp")          # otto_video.demo never removes its work dir: keep it in the workspace
        try:
            _, out, code = call(M["otto_video"].demo, str(reel), False)
        finally:
            tempfile.tempdir = None
        R.check(code == 0 and reel.exists(), f"otto_video demo render failed: {out[-300:]}")
        with ap.transaction(sync=False) as dd:
            for pid in ids:
                p = ap.post(dd, pid)
                if p.get("format") == "reel" and reel.exists():
                    shutil.copyfile(reel, paths.ASSETS / "reels" / f"{pid}.mp4")
                    p["video"] = f"assets/reels/{pid}.mp4"
        # the video script a reel gets from otto_video.plan_script: language of the closing line
        br = ap.brand(data(), slug)
        script = M["otto_video"].plan_script(ap.post(data(), ids[0]), br)
        last = script[-1]["text"]
        if b["expect"]["primary"] != "en" and LANG_MARKERS["en"].search(last):
            R.warn(f"reel script closing line is English for a {b['expect']['primary']} brand: “{last}”")
        cta = cre.cta_card_text(br)
        if b["expect"]["primary"] != "en" and LANG_MARKERS["en"].search(cta):
            R.warn(f"carousel CTA card is English for a {b['expect']['primary']} brand: “{cta}”")
        missing = [p["id"] for p in posts_of(slug) if p.get("plan") == ym and p["platform"] == "ig" and not p.get("image")]
        R.mark("PASS", f"{len(patches)} images · reel {reel.stat().st_size // 1024 if reel.exists() else 0} KB · IG posts without image: {missing}")


def step_compliance(b):
    comp, ap = M["otto_compliance"], M["ap"]
    slug = b["slug"]
    with R.step(slug, "compliance"):
        d = data()
        flagged = [p["id"] for p in posts_of(slug, d) if comp.check_post(p)]
        vio = IDS[slug].get("violator")
        if vio:
            R.check(vio in flagged, f"injected violation {vio} “{ap.post(d, vio)['hook'][:50]}” was NOT flagged "
                                    f"(no brands/{slug}/compliance.json and no baseline for a restricted category)")
            code, out, _ = cli("otto_compliance.py", "post", vio)
            R.check(code == 1, f"otto_compliance.py post {vio} exited {code} (expected 1 = violation)")
        clean_flagged = [x for x in flagged if x != vio]
        R.check(not clean_flagged, f"clean posts flagged (false positives): {clean_flagged[:5]}", "WARN")
        R.mark("PASS", f"{len(flagged)} flagged · rules file {'yes' if (WSP.root / 'brands' / slug / 'compliance.json').exists() else 'no'}")


PAST_CARDS = []


def step_telegram(biz):
    tg, ap = M["otto_telegram"], M["ap"]
    FakeClock.set("2026-09-30T05:00:00Z")           # 08:00 IL cron
    with R.step("ENGINE", "cards for past slots"):   # the cron has no --brand: the pilot brands' posts are in the same run
        n0 = len(TG.calls)
        d = data()
        _, out, code = call(tg.send_cards, None, 72, False, True)
        now = SimDatetime.now(timezone.utc)
        past = [p["id"] for p in d["posts"] if p["status"] == "pending_approval" and not p.get("tg_message_id")
                and (M["ap"].slot_dt(p, M["ap"].brand(d, p["brand"])) or now) < now and f"WOULD SEND {p['id']} " in out]
        R.check(not past, f"send-cards would send approval cards for {len(past)} post(s) whose slot already passed: {past[:6]}", "WARN")
        R.mark("PASS", f"{out.count('WOULD SEND')} would send across all brands")
    for b in biz:
        with R.step(b["slug"], "tg-dry"):
            n0 = len(TG.calls)
            _, out, code = call(tg.send_cards, b["slug"], 72, False, True)
            R.check(code == 0, f"send-cards --dry exited {code}")
            R.check(len(TG.calls) == n0, "--dry called the Telegram API")
            R.check(not [p for p in posts_of(b["slug"]) if p.get("tg_message_id") or p.get("compliance_block")], "--dry changed data.json")
            R.mark("PASS", f"{out.count('WOULD SEND')} would send · {out.count('BLOCKED')} blocked")
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "tg-cards"):
            n0 = len(TG.calls)
            _, out, code = call(tg.send_cards, slug, 72, False, False)
            R.check(code == 0, f"send-cards exited {code}")
            sent = [c for c in TG.calls[n0:] if c[0] in ("sendPhoto", "sendMessage")]
            d = data()
            carded = [p for p in posts_of(slug, d) if p.get("tg_message_id")]
            IDS[slug]["carded"] = [p["id"] for p in sorted(carded, key=lambda p: p["slot"])]
            R.check(len(sent) == len(carded), f"{len(sent)} API sends vs {len(carded)} posts with a card id")
            R.check(len(carded) >= 3, f"only {len(carded)} cards for the next 72 h", "WARN")
            now = SimDatetime.now(timezone.utc)
            past = [p["id"] for p in carded if ap.slot_dt(p, ap.brand(d, slug)) < now]
            R.check(not past, f"cards sent for slots already in the past: {past}", "WARN")
            vio = IDS[slug].get("violator")
            if vio:
                vp = ap.post(d, vio)
                R.check(not vp.get("tg_message_id"), f"violating post {vio} was sent to the owner")
                R.check(bool(vp.get("compliance_block")), f"violating post {vio} has no compliance_block", "WARN")
            for c in TG.calls[n0:]:
                if c[0] == "sendPhoto" and not c[2]:
                    R.check(c[1]["photo"].startswith("https://"), f"photo sent by non-https URL {c[1]['photo']}")
                cap = c[1].get("caption") or c[1].get("text") or ""
                R.check(len(cap) <= 1024 or c[0] == "sendMessage", "caption over 1024 chars")
            n1 = len(TG.calls)
            call(tg.send_cards, slug, 72, False, False)
            R.check(len(TG.calls) == n1, "second send-cards run re-sent cards (not idempotent)")
            kinds = sorted({c[0] for c in TG.calls[n0:n1] if c[0].startswith("send")})
            PAST_CARDS.extend(f"{c[1].get('caption') or c[1].get('text')}"[:60] for c in TG.calls[n0:n1] if c[0].startswith("send"))
            R.mark("PASS", f"{len(carded)} cards ({', '.join(kinds)}) · {out.count('BLOCKED')} blocked")


def cq(pid_or_rec, action, user=42, mid=None, photo=True):
    msg = {"message_id": mid or 900, "chat": {"id": 42}, "caption" if photo else "text": "card"}
    if photo:
        msg["photo"] = [{}]
    return {"id": "q", "from": {"id": user}, "data": f"otto:{pid_or_rec}:{action}", "message": msg}


def step_approvals(biz):
    tg, ap = M["otto_telegram"], M["ap"]
    FakeClock.set("2026-09-30T06:30:00Z")
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "approvals"):
            carded = IDS[slug].get("carded") or []
            if not R.check(len(carded) >= 3, f"not enough cards to decide on ({len(carded)})"):
                continue
            # 1) via the manual CLI (poller equivalent) · 2) via the Telegram callback handler
            code, out, _ = cli("ap.py", "decide", carded[0], "approve", "--via", "telegram")
            R.check(code == 0 and "approved" in out, f"ap.py decide failed: {out[-200:]}")
            call(tg.handle_callback, cq(carded[1], "approve"))
            R.check(ap.post(data(), carded[1])["status"] == "approved", "Telegram ✅ did not approve")
            n0 = len(TG.calls)
            call(tg.handle_callback, cq(carded[1], "approve"))
            answer = [c[1].get("text", "") for c in TG.calls[n0:] if c[0] == "answerCallbackQuery"]
            t = M["otto_i18n"].Tr.for_brand(ap.brand(data(), slug))           # the client's language (Dutch, German, …)
            R.check(answer and answer[-1].startswith(t("tg.already", state="").strip()), f"double tap answered {answer}")
            call(tg.handle_callback, cq(carded[2], "approve", user=7))
            R.check(ap.post(data(), carded[2])["status"] == "pending_approval", "a non-owner tap changed state")
            rest = carded[2:]
            if slug == "spreebogen" and len(rest) >= 2:              # ✏️ Edit → reply to the prompt → draft + edit request
                call(tg.handle_callback, cq(rest[0], "edit"))
                prompt_id = TG.mid
                call(tg.handle_message, {"from": {"id": 42}, "chat": {"id": 42}, "text": "Kürzer, und bitte den Samstagstermin erwähnen",
                                         "reply_to_message": {"message_id": prompt_id}})
                q = ap.post(data(), rest[0])
                R.check(q["status"] == "draft" and "Samstag" in (q.get("edit_note") or ""), f"edit not stored: {q['status']} {q.get('edit_note')}")
                # Quill rewrites it (ap.py set) and re-sends exactly that card (send-cards --ids)
                code, out, _ = cli("ap.py", "set", rest[0], json.dumps({"hook": "Zahnreinigung am Samstag: kurz erklärt",
                                                                        "caption": "Kurz und klar: so läuft die Zahnreinigung am Samstag.",
                                                                        "status": "pending_approval"}, ensure_ascii=False))
                R.check(code == 0, f"ap.py set failed: {out[-200:]}")
                n0 = len(TG.calls)
                call(tg.send_cards, None, 72, False, False, M["otto_telegram"].BASE, {rest[0]})
                R.check(any(c[0].startswith("send") and "Samstag" in str(c[1]) for c in TG.calls[n0:]), "rewritten post was not re-sent as a card")
                rest = rest[1:]
            if slug == "ondaviva" and rest:
                call(tg.handle_callback, cq(rest[0], "later"))
                q = ap.post(data(), rest[0])
                R.check(q["status"] == "pending_approval" and not q.get("tg_message_id"), "↷ Later did not clear the card")
                rest = rest[1:]
            if rest:
                code, out, _ = cli("ap.py", "decide", rest[0], "skip", "--via", "dashboard")
                R.check(code == 0 and "skipped" in out, f"skip failed: {out[-200:]}")
                rest = rest[1:]
            for pid in rest:
                call(tg.handle_callback, cq(pid, "approve"))
            # the owner also approves every other Oct 1 post from the dashboard deck (no card)
            d = data()
            extra = [p["id"] for p in posts_of(slug, d) if p["status"] == "pending_approval" and p["slot"].startswith("2026-10-01")
                     and p["id"] != IDS[slug].get("violator")]
            for pid in extra:
                M["otto_api"].apply_decision(pid, "approve", "dashboard")
            d = data()
            st = {}
            for p in posts_of(slug, d):
                if p.get("plan") == "2026-10" and p["slot"] < "2026-10-03":
                    st[p["status"]] = st.get(p["status"], 0) + 1
            taste = [t for t in d.get("taste_log", []) if t["brand"] == slug]
            R.check(len(taste) >= 3, f"taste log has {len(taste)} decisions")
            code, out, _ = cli("ap.py", "taste", slug)
            R.check(code == 0 and "✓" in out, f"ap.py taste failed: {out[-200:]}")
            R.mark("PASS", f"first 2 days: {st} · taste log {len(taste)}")


def step_publish(biz):
    pub, ap = M["otto_publish"], M["ap"]
    # failure injections on Oct 1 09:00 posts
    inj = {}
    for b in biz:
        d = data()
        oct1 = [p for p in posts_of(b["slug"], d) if p["status"] == "approved" and p["slot"].startswith("2026-10-01T09")]
        if not oct1:
            continue
        if b["slug"] == "spreebogen":
            META.inject[oct1[0]["id"]] = "timeout"; inj["timeout"] = oct1[0]["id"]
        if b["slug"] == "grachtenkoffie":
            META.inject[oct1[0]["id"]] = "graph_error_once"; inj["graph_error_once"] = oct1[0]["id"]
    # a violating post approved straight from the dashboard (no card → no compliance check on the way)
    vio = IDS.get("ofek", {}).get("violator")
    if vio:
        with ap.transaction(sync=False) as dd:
            p = ap.post(dd, vio)
            p["slot"] = "2026-10-01T10:00"
            p["status"] = "pending_approval"; p.pop("compliance_block", None)
        M["otto_api"].apply_decision(vio, "approve", "dashboard")
        inj["compliance_bypass"] = vio
    ng = IDS.get("studiolume", {}).get("no_image")
    if ng:
        with ap.transaction(sync=False) as dd:
            p = ap.post(dd, ng)
            p["slot"] = "2026-10-01T09:30"; p["status"] = "approved"
        inj["no_image"] = ng
    IDS["_inject"] = inj
    FakeClock.set("2026-10-01T06:50:00Z")
    for b in biz:
        with R.step(b["slug"], "publish-dry"):
            snap = json.dumps(posts_of(b["slug"]), sort_keys=True)
            n0 = len(META.calls)
            _, out, code = call(pub.run, True, b["slug"])
            R.check(len(META.calls) == n0, "--dry called Graph")
            R.check(json.dumps(posts_of(b["slug"]), sort_keys=True) == snap, "--dry changed data.json")
            R.mark("PASS", f"{out.count('WOULD PUBLISH')} would publish at {FakeClock.now:%H:%M}Z")
    runs = ["2026-10-01T07:10:00Z", "2026-10-01T08:20:00Z", "2026-10-01T09:05:00Z", "2026-10-01T16:05:00Z", "2026-10-01T20:30:00Z",
            "2026-10-02T07:05:00Z", "2026-10-02T09:20:00Z"]
    outs = {}
    for t in runs:
        FakeClock.set(t)
        _, out, code = call(pub.run)
        outs[t] = out
        if code:
            R.mark("FAIL", f"publisher exited {code} at {t}", ("ENGINE", "publish"))
    d = data()
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "publish"):
            mine = [p for p in posts_of(slug, d) if p.get("plan") == "2026-10" and p["slot"] < "2026-10-03"]
            st = {}
            for p in mine:
                st[p["status"]] = st.get(p["status"], 0) + 1
            pubs = [pid for pid, _ in META.published if pid and pid.startswith(ap.id_prefix(d, slug) + "-")]
            dup = sorted({x for x in pubs if pubs.count(x) > 1})
            R.check(not dup, f"DOUBLE POST on Meta: {dup}")
            br = ap.brand(d, slug)
            for p in mine:
                if p["status"] == "published":
                    R.check(bool(p.get("remote_id")), f"{p['id']} published without remote_id")
                    loc = ap.slot_dt(p, br).astimezone(ZoneInfo(b["expect"]["tz"]))
                    R.check(7 <= loc.hour <= 21, f"{p['id']} went out at {loc:%H:%M} local", "WARN")
            if slug == "spreebogen" and inj.get("timeout"):
                q = ap.post(d, inj["timeout"])
                R.check(q["status"] == "publishing", f"timeout post is {q['status']} (must stay publishing, never retried)")
                n = sum(1 for c in META.calls if c["pid"] == inj["timeout"] and c["final"])
                R.check(n == 1, f"timeout post hit the publish endpoint {n}×")
                R.check(any(r.get("post") == inj["timeout"] and r["priority"] == "P0" for r in d["recommendations"]), "no P0 'check if it went out'")
            if slug == "grachtenkoffie" and inj.get("graph_error_once"):
                q = ap.post(d, inj["graph_error_once"])
                R.check(q["status"] == "published" and q.get("attempts") == 1, f"Meta error then retry: {q['status']} attempts {q.get('attempts')}")
            if slug == "ofek" and inj.get("compliance_bypass"):
                q = ap.post(d, inj["compliance_bypass"])
                R.check(q["status"] != "published", f"a compliance-violating post approved from the dashboard was PUBLISHED ({q['id']} “{q['hook'][:40]}”)")
            if slug == "studiolume" and inj.get("no_image"):
                q = ap.post(d, inj["no_image"])
                R.check(q["status"] == "failed", f"IG post without image: {q['status']} attempts {q.get('attempts')} error {q.get('error')}")
                R.check(any(r.get("post") == q["id"] and r["priority"] == "P0" for r in d["recommendations"]), "no P0 for the post that never went out")
            missed = [p["id"] for p in mine if p["status"] == "failed" and "missed" in (p.get("error") or "")]
            R.mark("PASS", f"{st} · missed {missed} · Meta publish calls {len(pubs)}")


def step_ads(biz, ym):
    ads, ap, tg = M["otto_ads"], M["ap"], M["otto_telegram"]
    FakeClock.set("2026-09-30T08:00:00Z")
    for b in biz:
        slug = b["slug"]
        META.acct_currency[f"act_{slug}"] = b["meta"]["acct_currency"]
        with R.step(slug, "ads-plan"):
            code, out, _ = cli("otto_ads.py", "plan", slug, ym, "--dry")
            R.check(code == 0, f"ads plan --dry exited {code}: {out[-300:]}")
            _, out, code = call(ads.plan, slug, ym, 20.0, False)
            R.check(code == 0, f"ads plan exited {code}: {out[-300:]}")
            d = data()
            cps = [c for c in d.get("campaigns", []) if c["brand"] == slug and c.get("plan") == ym]
            R.check(len(cps) >= 3, f"{len(cps)} flights planned")
            exp_cur = b["expect"]["currency"] or "EUR"
            R.check(all(c["currency_code"] == exp_cur for c in cps), f"plan currency {[c['currency_code'] for c in cps][:1]} (expected {exp_cur})", "WARN")
            countries = cps[0]["audience"]["countries"] if cps else []
            R.check(countries == b["expect"]["countries"], f"audience countries {countries} (business sells in {b['expect']['countries']})", "WARN")
            R.check(all(c.get("landing_url", "").startswith("http") for c in cps), "flight without a landing URL")
            lp = b.get("landing")
            if isinstance(lp, str):
                R.check(all(c["landing_url"] == lp for c in cps), f"landing {[c['landing_url'] for c in cps][:2]} (brand landing {lp})")
            elif isinstance(lp, dict):
                by = {c["stage"]: c["landing_url"] for c in cps}
                R.check(by.get("hot") == lp["hot"] and by.get("cold") == "https://ondaviva-surf.com/en/",
                        f"per-stage landing wrong: {by} (cache-buster must be stripped, hot → pricing page)")
                R.check(by.get("warm") == "https://ondaviva-surf.com/en/", f"warm stage falls back to cold: {by.get('warm')}")
            g = [c for c in cps if c["network"] == "google"]
            for c in g:
                try:
                    heads, descs = ads.rsa_assets(c, ap.brand(d, slug), (c["audience"].get("languages") or ["en"])[0])
                except ads.LaunchError as e:
                    R.fail(f"Google RSA cannot be built: {e}"); continue
                eng = [h for h in heads + descs if LANG_MARKERS["en"].search(h) or h in ("Official Site", "Learn More Today", "Get in Touch")]
                if b["expect"]["primary"] != "en" and eng:
                    R.warn(f"Google RSA for a {b['expect']['primary']} brand carries English fallback copy: {eng[:3]}")
                lang = (c["audience"].get("languages") or [None])[0]
                if lang not in ads.LANG_CONST:
                    R.warn(f"no Google language constant for '{lang}' — Search campaign would run without a language criterion")
            rec = next((r for r in d["recommendations"] if r.get("brand") == slug and r.get("action") == "approve_plan"), None)
            R.check(rec is not None, "no 'Approve the paid plan' card")
            held = [c["id"] for c in cps if c.get("compliance_hold")]
            R.mark("PASS", f"{len(cps)} flights · {sorted({c['network'] for c in cps})} · hold {len(held)} · {cps[0]['currency'] if cps else ''}"
                           f" · countries {countries}")
            if rec:
                n0 = len(TG.calls)
                call(tg.handle_callback, cq(f"rec:{rec['id']}".replace("rec:", "rec:"), "approve", photo=False))
                ans = [c[1].get("text", "") for c in TG.calls[n0:] if c[0] == "answerCallbackQuery"]
                t = M["otto_i18n"].Tr.for_brand(M["ap"].brand(data(), slug))
                R.check(ans and ans[-1] == t("tg.rec.on_it"), f"approving the plan card did not run approve(): {ans}")
    FakeClock.set("2026-10-01T03:00:00Z")          # 06:00 IL launch cron, day 1
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "ads-launch"):
            code, out, _ = cli("otto_ads.py", "launch", "--brand", slug, "--dry", env={"OTTO_SIM_NOW": "2026-10-01"})
            n0 = len(META.calls)
            _, outd, code = call(ads.launch, slug, True)
            R.check(len(META.calls) == n0 or all(c["m"] == "GET" for c in META.calls[n0:]), "launch --dry created objects")
            _, out, code = call(ads.launch, slug, False)
            R.check(code == 0, f"launch exited {code}: {out[-300:]}")
            n1 = len(META.calls)
            _, out2, _ = call(ads.launch, slug, False)          # re-run the same day: nothing new may be created
            created = [c for c in META.calls[n1:] if c["m"] == "POST" and c["path"].split("/")[-1] in ("campaigns", "adsets", "ads")]
            R.check(not created, f"second launch run created {len(created)} more Meta objects")
            d = data()
            cps = [c for c in d.get("campaigns", []) if c["brand"] == slug and c.get("plan") == ym]
            st = {c["id"]: c["status"] for c in cps}
            errs = {c["id"]: (c.get("error") or "")[:90] for c in cps if c.get("error")}
            if slug == "spreebogen":
                gc = next((c for c in cps if c["network"] == "google"), None)
                if gc:
                    R.check(gc["status"] == "failed" and "invalid_grant" in (gc.get("error") or ""),
                            f"Google invalid_grant: {gc['status']} hold={gc.get('compliance_hold')} {gc.get('error')}")
                    R.check(any(r.get("campaign_id") == gc["id"] and r["priority"] == "P0" for r in d["recommendations"]),
                            "no P0 card for the Google launch that failed on invalid_grant")
            if slug == "grachtenkoffie":
                mc = next((c for c in cps if c["network"] == "meta" and c["start"] == "2026-10-01"), None)
                if mc:
                    R.check(mc["status"] == "failed" and "USD" in (mc.get("error") or ""), f"currency mismatch not refused: {mc['status']} {mc.get('error')}")
            if slug == "studiolume":
                R.check(any(r.get("brand") == slug and "onnect" in r["title"] for r in d["recommendations"]),
                        "approved paid plan cannot launch (no ad account / Google) and nobody is told — no 'connect' card", "WARN")
            live = [c for c in cps if c["status"] == "live"]
            for c in live:
                cr = c.get("creatives") or {}
                imgs = [i for i in cr.get("images", []) if not i.get("note")]
                R.check(imgs or c["network"] == "google" or (c.get("remote") or {}).get("mode", {}).get("boost"),
                        f"{c['id']} went live without rendered statics: {[i.get('note') for i in cr.get('images', [])][:2]}", "WARN")
                if b["expect"]["primary"] == "he":
                    R.check(any(M["otto_creative"].RTL.search(t or "") for t in cr.get("titles", [])), "Hebrew brand ad titles are not Hebrew", "WARN")
                for t in cr.get("bodies", []):
                    if re.search(r"—\s*$|\(\?\)|TBD", t):
                        R.warn(f"ad body looks unfinished: “{t[:60]}”")
            R.mark("PASS", f"{st} · errors {errs}")
    # boosts need a post live on Facebook: jump to the first boost day
    FakeClock.set("2026-10-08T03:00:00Z")
    for b in biz:
        _, out, _ = call(ads.launch, b["slug"], False)
        d = data()
        boosts = [c for c in d.get("campaigns", []) if c["brand"] == b["slug"] and c.get("objective") == "engagement" and c["start"] == f"{ym}-08"]
        for c in boosts:
            live_fb = [p["id"] for p in posts_of(b["slug"], d) if p["status"] == "published" and p["platform"] == "fb" and p.get("image")]
            if c["status"] == "skipped" and live_fb:
                with R.step(b["slug"], "ads-launch"):
                    R.warn(f"boost {c['id']} skipped on Oct 8: planned post {c['creative'].get('post')} is not live on FB "
                           f"(live FB posts available: {live_fb[:3]}) — boosts picked at plan time can never run for a new brand")


def step_insights(biz):
    ins, ap = M["otto_insights"], M["ap"]
    FakeClock.set("2026-10-02T03:00:00Z")
    d = data()
    for p in d["posts"]:
        if p.get("remote_id"):
            n = int(hashlib.md5(p["id"].encode()).hexdigest()[:4], 16) % 900 + 100
            META.post_metrics[p["remote_id"]] = {"post_total_media_view_unique": n * 3, "post_media_view": n * 4, "post_clicks": n // 10,
                                                 "reach": n * 3, "views": n * 4, "saved": n // 20,
                                                 "likes": n // 5, "comments": 3, "shares": 2}
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "insights"):
            n0 = len(META.calls)
            _, out, code = call(ins.run, True, slug)
            R.check(len(META.calls) == n0, "--dry called Graph")
            _, out, code = call(ins.run, False, slug)
            R.check(code == 0, f"insights exited {code}")
            _, out2, _ = call(ins.run, False, slug)
            d = data()
            recs = [r for r in d["recommendations"] if r.get("brand") == slug and r.get("source") == "otto_insights"]
            R.check(len(recs) <= 1, f"{len(recs)} 'double down' recs after two runs (duplicate)")
            withm = [p for p in posts_of(slug, d) if p.get("metrics") and "error" not in p["metrics"]]
            R.mark("PASS", f"{len(withm)} posts with metrics · metrics[{slug}] = {d.get('metrics', {}).get(slug)} · recs {len(recs)}")
        with R.step(slug, "insights-daily"):
            n0 = len(META.calls)
            _, out, code = call(ins.daily, slug)
            R.check(code == 0, f"insights daily exited {code}")
            asked = ",".join(c["path"] for c in META.calls[n0:])
            R.check(f"IG{slug}/insights" in asked and f"PG{slug}/insights" in asked, "daily asked neither Instagram nor the Page")
            m = (data().get("metrics") or {}).get(slug) or {}
            R.check(isinstance(m.get("baseline"), dict) and m["baseline"].get("days") == 30, f"no 30-day baseline: {m.get('baseline')}")
            R.check(((m.get("account") or {}).get("ig") or {}).get("followers") == 1500, f"Instagram followers missing: {m.get('account')}")
            R.check(not (m.get("account") or {}).get("errors"), f"account pull errors: {(m.get('account') or {}).get('errors')}")
            R.mark("PASS", f"{len(m.get('daily') or {})} day(s) · baseline {m['baseline']['since']}…{m['baseline']['until']}")


def step_ads_report(biz):
    ads, ap = M["otto_ads"], M["ap"]
    for b in biz:
        slug = b["slug"]
        act = f"act_{slug}"
        META.ads_rows[act] = lambda preset, s=slug: [
            {"campaign_id": "CAM-good", "campaign_name": f"{s} evergreen", "objective": "OUTCOME_LEADS", "spend": "40.00", "impressions": "5000",
             "reach": "4000", "clicks": "120", "inline_link_clicks": "90", "ctr": "2.4", "actions": [{"action_type": "lead", "value": "8"}]},
            {"campaign_id": "CAM-bad", "campaign_name": f"{s} test", "objective": "OUTCOME_LEADS", "spend": "30.00", "impressions": "3000",
             "reach": "2500", "clicks": "20", "inline_link_clicks": "15", "ctr": "0.6", "actions": [{"action_type": "lead", "value": "1"}]}]
    for i, day in enumerate(["2026-10-02", "2026-10-03", "2026-10-04"]):
        FakeClock.set(day + "T04:35:00Z")
        for b in biz:
            with R.step(b["slug"], "ads-report"):
                if i == 0:
                    _, out, code = call(ads.report, b["slug"], 7, True, False)
                    R.check(code == 0, "report --dry failed")
                _, out, code = call(ads.report, b["slug"], 7, False, False)
                R.check(code == 0, f"report exited {code}: {out[-200:]}")
    d = data()
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "ads-report"):
            recs = [r for r in d["recommendations"] if r.get("brand") == slug and r.get("source") == "otto_ads"]
            pause = [r for r in recs if r.get("action") == "pause_campaign"]
            recon = [r for r in recs if r["title"].startswith("Reconnect Google")]
            if b["meta"]["ad_account"]:
                R.check(len(pause) == 1, f"{len(pause)} pause cards after 3 days above target CPL (expected 1)", "WARN")
            if b["google"] and b["google"]["revoked"]:
                R.check(len(recon) == 1, f"{len(recon)} 'Reconnect Google Ads' cards after 3 reports with invalid_grant (expected 1)")
            n0 = len(TG.calls)
            call(M["otto_telegram"].send_recs, False)
            mine = [r for r in data()["recommendations"] if r.get("brand") == slug and r["status"] == "proposed"]
            R.check(all(r.get("tg_message_id") for r in mine), f"{sum(1 for r in mine if not r.get('tg_message_id'))} proposed rec(s) got no card")
            n1 = len(TG.calls)
            call(M["otto_telegram"].send_recs, False)
            R.check(len(TG.calls) == n1, "send-recs re-sent recommendation cards")
            daily = (d.get("ads", {}).get(slug) or {}).get("daily", {})
            cur = [v.get("meta", {}).get("currency") for v in daily.values() if v.get("meta")]
            exp = b["meta"]["acct_currency"]
            R.check(all(c == exp for c in cur), f"report currency {cur[:1]} vs ad account {exp}", "WARN")
            R.mark("PASS", f"{len(daily)} days · pause cards {len(pause)} · reconnect cards {len(recon)}")


def step_watch(biz):
    w, ap = M["otto_watch"], M["ap"]
    # publisher down: an approved post 3 h past its slot and nothing ran since → the hourly guard must say so
    d = data()
    target = None
    for b in biz:
        cand = sorted([p for p in posts_of(b["slug"], d) if p["status"] == "pending_approval" and p["slot"].startswith("2026-10-05")],
                      key=lambda p: p["slot"])
        if cand:
            target = (b["slug"], cand[0]["id"]); break
    if target:
        M["otto_api"].apply_decision(target[1], "approve", "dashboard")
    FakeClock.set("2026-10-05T11:30:00Z")
    n0 = len(SENT)
    _, out, code = call(w.watch)
    alerts = "\n".join(t for _, t in SENT[n0:])
    for b in biz:
        with R.step(b["slug"], "watch"):
            R.check(code == 0, f"watch exited {code}: {out[-200:]}")
            if b["slug"] == "spreebogen":                                         # a German brand: its alert is German
                unq = lambda x: re.sub(r"[“”‘’„]", "", x)
                frag = unq(M["otto_i18n"].Tr.for_brand(ap.brand(data(), "spreebogen"))("alert.stuck", hook=""))[:40].strip()
                R.check(frag in unq(alerts), "no alert for the post stuck in publishing")
            if target and b["slug"] == target[0]:
                hook = ap.post(data(), target[1])["hook"][:30]
                R.check(hook[:20] in alerts, f"publisher down: approved post {target[1]} is 2+ h past its slot and the hourly guard said nothing "
                                             f"(it only checks data.json connections[], which new brands never get)", "WARN")
    n1 = len(SENT)
    call(w.watch)
    for b in biz[:1]:
        with R.step(b["slug"], "watch"):
            R.check(len(SENT) == n1, "second watch run re-sent the same alerts (dedup)")
    FakeClock.set("2026-10-06T04:30:00Z")
    _, out, code = call(w.report)
    text = SENT[-1][1] if len(SENT) > n1 else ""
    for b in biz:
        with R.step(b["slug"], "watch"):
            R.check(code == 0, f"report exited {code}: {out[-200:]}")
            R.mark("PASS", f"alerts {len(alerts.split(chr(10) + chr(10))) - 1 if alerts else 0} · morning report {len(text)} chars")
    with R.step("ENGINE", "isolation"):
        for f in ("metrics_history.jsonl", ".watch-state.json"):
            real = PLATFORM / f
            if real.exists() and FakeClock.now and "2026-10" in real.read_text()[-400:]:
                R.fail(f"otto_watch wrote the simulation into the REAL platform/{f}")


def step_growth(biz):
    g, ap = M["otto_growth"], M["ap"]
    SENT_TG0 = len(TG.calls)
    FakeClock.set("2026-11-01T02:10:00Z")
    _, out, code = call(g.rollup, True)
    _, out2, code2 = call(g.rollup, True)
    reviews = [c for c in TG.calls[SENT_TG0:] if c[0] == "sendMessage" and "in review" in c[1].get("text", "")]
    d = data()
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "growth"):
            R.check(code == 0 and code2 == 0, f"rollup exited {code}/{code2}: {out[-300:]}")
            R.check(len(reviews) == 1, f"{len(reviews)} month-in-review messages after two rollup --send runs (expected 1)")
            gr = (d.get("growth") or {}).get(slug)
            if not R.check(gr is not None, "no growth entry"):
                continue
            sym = M["ap"].currency_symbol(b["expect"]["currency"] or "EUR").strip()
            rv = M["otto_growth"].review_text(M["ap"].brand(d, slug), gr, "2026-10")
            if gr["months"]["2026-10"].get("spend"):
                R.check(sym in rv, f"month review shows spend without the brand currency {sym}: {rv[-120:]}", "WARN")
            oct_ = gr["months"].get("2026-10") or {}
            R.check(gr["previous"] == "2026-10", f"previous month {gr['previous']} on Nov 1")
            R.check(oct_.get("posts", 0) >= 1, f"October shows {oct_.get('posts')} published posts", "WARN")
            exp = b["expect"]["currency"] or "EUR"
            R.check(gr["currency"] == exp, f"growth currency {gr['currency']} (expected {exp})", "WARN")
            code3, out3, _ = cli("otto_growth.py", "show", slug)
            R.check(code3 == 0, f"growth show exited {code3}: {out3[-200:]}")
            R.mark("PASS", f"Oct: posts {oct_.get('posts')} reach {oct_.get('reach')} spend {oct_.get('spend')} · MoM {gr['mom'].get('reach')}")


def step_demo(biz):
    demo = M["otto_demo"]
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "demo"):
            out_f = WSP.root / "demo" / f"{slug}-journey.json"
            if "otto_demo" in UNSAFE_CLI:
                _, out, code = call(demo.journey, slug, 90, 7, str(out_f))
            else:
                code, out, _ = cli("otto_demo.py", "journey", slug, "--out", str(out_f))
            R.check(code == 0, f"journey exited {code}: {out[-300:]}")
            if not R.check(out_f.exists(), "journey json not written"):
                continue
            doc = json.loads(out_f.read_text())
            R.check(doc["brand"].get("name") == b["name"], f"demo brand name {doc['brand'].get('name')!r} (read the wrong data.json?)")
            A = doc["assumptions"]
            exp = M["ap"].currency_symbol(b["expect"]["currency"] or "EUR")
            R.check(A.get("currency", "").strip() == exp.strip(), f"demo currency {A.get('currency')} (expected {exp})", "WARN")
            R.check("CBD" not in A.get("paid_note", "") or "cbd" in slug, f"demo paid note talks about CBD: “{A.get('paid_note', '')[:70]}”", "WARN")
            R.check(len(doc["series"]) == 90, f"{len(doc['series'])} days simulated")
            R.check(bool(doc["real"]["palette"]), "demo has no real palette (scan not read)", "WARN")
            R.mark("PASS", f"{len(doc['months'])} months · currency {A.get('currency')}")


def step_reels(biz):
    mo, ap = M["otto_motion"], M["ap"]
    for b in biz:
        slug = b["slug"]
        with R.step(slug, "reels"):
            d = data()
            reel = next((p for p in posts_of(slug, d) if p.get("format") == "reel"), None)
            if not R.check(reel is not None, "no reel post"):
                continue
            ran = []
            orig = mo.sh
            def fake_sh(cmd, cwd=None, check=True, both=False):
                ran.append(cmd[:3])
                if "init" in cmd:
                    Path(cmd[4]).mkdir(parents=True, exist_ok=True)
                return ""
            mo.sh = fake_sh
            try:
                _, out, code = call(mo.prepare, reel["id"], 45)
            finally:
                mo.sh = orig
            R.check(code == 0, f"motion prepare exited {code}: {out[-300:]}")
            brief = Path(mo.MOTION) / f"{slug}-{reel['id']}" / "BRIEF.md"
            if R.check(brief.exists(), "BRIEF.md not written"):
                lang = re.search(r"^language:\s*(\w+)", brief.read_text(), re.M).group(1)
                R.check(lang == b["expect"]["primary"], f"reel BRIEF language '{lang}' for a {b['expect']['primary']} brand — the voice-over "
                                                          f"and captions would be produced in the wrong language", "WARN")
                R.check(str(brief.resolve()).startswith(str(WSP.root.resolve())), "motion project written outside the workspace")
            R.skip("HyperFrames render / ElevenLabs voice / faster-whisper not exercised offline (npx + network)")
            R.mark("PASS", f"prepare ok (external calls stubbed: {len(ran)})")


# ============================================================================================
# failure injections not tied to one business
# ============================================================================================

def inject_bad_sites():
    sc = M["otto_scan"]
    junk = (b"<html><head><meta charset='x-bogus'><title>Bro<ken</title><meta name='theme-color' content='javascript:alert(1)'>"
            b"<style>a{color:#GGGGGG} b{color:#12}</style></head><body><div class='review'>" + b"\x00\xff\xfe\x80" * 3000 +
            b"<div>" * 4000 + b"<a href='/about'>about</a><a href='//evil.example/about'>x</a>" + b"<h1>" * 50 + b"&#xFFFFFF; &bogus; <![CDATA[")
    srv, url, _ = serve({}, special={"/": (200, {"Content-Type": "text/html; charset=x-bogus"}, junk),
                                     "/about": (200, {"Content-Type": "text/html"}, b"<p>" + "ü".encode("latin-1") * 500),
                                     "/meta": (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""),
                                     "/private": (301, {"Location": "http://10.0.0.5/admin"}, b""),
                                     "/loop": (302, {"Location": "/loop"}, b""),
                                     "/err": (500, {"Content-Type": "text/html"}, b"oops"),
                                     "/pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 \x00\x01")})
    sc.ALLOWED_PORTS = sc.ALLOWED_PORTS | {srv.server_address[1]}
    with R.step("INJECT", "malformed site"):
        _, out, code = call(sc.run_cli, [url + "/", "--slug", "junk"])
        R.check(code == 0, f"malformed site crashed the scanner: {out[-300:]}")
        s = json.loads((WSP.root / "brands" / "junk" / "scan.json").read_text()) if (WSP.root / "brands" / "junk" / "scan.json").exists() else {}
        R.check("javascript" not in json.dumps(s.get("visual", {})), "theme-color javascript: leaked into the palette")
        _, out2, code2 = call(sc.run_cli, [url + "/pdf", "--slug", "junkpdf"])
        R.mark("PASS", f"scan exit {code} · industry {s.get('industry')} · pdf exit {code2}")
    for path, label in (("/meta", "redirect → 169.254.169.254"), ("/private", "redirect → 10.0.0.5"), ("/loop", "redirect loop"),
                        ("/err", "HTTP 500")):
        with R.step("INJECT", label):
            slug = "inj" + re.sub(r"\W", "", path)
            _, out, code = call(sc.run_cli, [url + path, "--slug", slug])
            R.check(code != 0 and "scan failed" in out, f"expected a clean refusal, got exit {code}: {out[-200:]}")
            R.check(not (WSP.root / "brands" / slug).exists(), "a brand folder was created for a refused URL")
            R.mark("PASS", out.strip().splitlines()[-1][:110] if out.strip() else "")
    with R.step("INJECT", "peek endpoint (landing)"):
        srv2, url2, _ = serve(site_ondaviva())
        sc.ALLOWED_PORTS = sc.ALLOWED_PORTS | {srv2.server_address[1]}
        code, r = M["otto_api"].peek(url2 + "/", "203.0.113.10")
        R.check(code == 200 and r.get("title") and r.get("palette"), f"peek of a normal site failed: {code} {str(r)[:160]}")
        R.check(r.get("currency") == "EUR" and r.get("languages", [None])[0] == "pt", f"peek currency/lang {r.get('currency')} {r.get('languages')}", "WARN")
        R.mark("PASS", f"{code} · {r.get('title', '')[:40]} · {r.get('industry')} · {r.get('pages')} pages")
        srv2.shutdown()
    with R.step("INJECT", "peek endpoint SSRF"):
        r = M["otto_api"].peek(url + "/meta", "203.0.113.9")
        R.check(r[0] != 200, f"peek followed the metadata redirect: {str(r)[:200]}")
        R.mark("PASS", str(r)[:110])
    srv.shutdown()


def inject_bad_compliance_json():
    comp = M["otto_compliance"]
    with R.step("INJECT", "corrupt compliance.json"):
        f = WSP.root / "brands" / "happygarden" / "compliance.json"
        good = f.read_text()
        f.write_text(good[: len(good) // 2])               # truncated mid-write
        try:
            v = comp.check_texts("happygarden", ["CBD cures insomnia"])
            R.check(bool(v), "an unreadable compliance.json lets every claim through (fails open) — 'CBD cures insomnia' passed")
        finally:
            f.write_text(good)
        R.mark("PASS", f"violations reported: {len(v)}")


CHILD = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["SIM_TESTS"]); sys.path.insert(0, os.environ["SIM_PLATFORM"])
import simulate as S
S.FakeClock.set(os.environ["SIM_NOW"])
import ap, otto_publish, otto_telegram, otto_ads, otto_growth, otto_watch
S.install_clock([ap, otto_publish, otto_telegram, otto_ads, otto_growth, otto_watch])
meta = S.FakeMeta(log_file=os.environ["SIM_LOG"], delay=float(os.environ.get("SIM_DELAY", "0.2")))
meta.acct_currency.update(json.loads(os.environ.get("SIM_ACCT", "{}")))
otto_publish.graph = meta.graph
tg = S.FakeTelegram(log_file=os.environ["SIM_LOG"], delay=float(os.environ.get("SIM_DELAY", "0.2")))
otto_telegram.api = tg.api
otto_watch.send = lambda text: tg.api("sendMessage", text=text) or True
import urllib.request; urllib.request.urlopen = S.FakeGoogle().urlopen
job = os.environ["SIM_JOB"]
if job == "publish": otto_publish.run()
elif job == "cards": otto_telegram.send_cards(os.environ.get("SIM_BRAND"))
elif job == "growth": otto_growth.rollup(send=True)
elif job == "launch": otto_ads.launch(os.environ.get("SIM_BRAND"))
'''


def run_pair(job, now, brand=None, delay="0.2", acct=None):
    log = WSP.root / "calls" / f"{job}-{int(time.time() * 1000)}.jsonl"
    env = dict(os.environ, **WSP.env, SIM_TESTS=str(TESTS), SIM_PLATFORM=str(PLATFORM), SIM_NOW=now, SIM_LOG=str(log), SIM_JOB=job,
               SIM_DELAY=delay, SIM_BRAND=brand or "", SIM_ACCT=json.dumps(acct or {}))
    procs = [subprocess.Popen([sys.executable, "-c", CHILD], cwd=str(PLATFORM), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True) for _ in range(2)]
    outs = [p.communicate(timeout=300)[0] for p in procs]
    rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return rows, outs, [p.returncode for p in procs]


def inject_parallel(ym):
    ap = M["ap"]
    # publish ×2
    with R.step("INJECT", "2× publish in parallel"):
        d = data()
        now = _real_datetime(2026, 10, 6, 16, 20, tzinfo=timezone.utc)
        ids = [p["id"] for b in BIZ[:2] for p in posts_of(b["slug"], d) if p["status"] == "pending_approval" and p["slot"].startswith("2026-10-06")][:6]
        with ap.transaction(sync=False) as dd:
            for pid in ids:
                q = ap.post(dd, pid)
                q["status"] = "approved"
                q["slot"] = (now - timedelta(minutes=10)).astimezone(ap.brand_tz(ap.brand(dd, q["brand"]))).strftime("%Y-%m-%dT%H:%M")
        rows, outs, codes = run_pair("publish", "2026-10-06T16:20:00Z")
        finals = [r["pid"] for r in rows if r.get("final")]
        dup = sorted({x for x in finals if finals.count(x) > 1})
        R.check(all(c == 0 for c in codes), f"child exit codes {codes}: {outs[0][-200:]}")
        R.check(not dup, f"DOUBLE POST: {dup} published by both processes")
        st = [ap.post(data(), pid)["status"] for pid in ids]
        R.check(all(s == "published" for s in st), f"statuses after the race: {st}", "WARN")
        R.mark("PASS", f"{len(ids)} due posts · {len(finals)} publish calls · statuses {sorted(set(st))}")
    # send-cards ×2
    with R.step("INJECT", "2× send-cards in parallel"):
        d = data()
        with ap.transaction(sync=False) as dd:
            for p in dd["posts"]:
                if p["brand"] in ("ondaviva", "studiolume") and p["status"] == "pending_approval" and "2026-10-07" <= p["slot"] < "2026-10-09":
                    p.pop("tg_message_id", None)
        rows, outs, codes = run_pair("cards", "2026-10-06T05:00:00Z", delay="0.3")
        sends = [r["text"] for r in rows if r["m"] in ("sendPhoto", "sendMessage")]
        dups = len(sends) - len(set(sends))
        R.check(dups == 0, f"{dups} duplicate approval card(s) — both processes sent the same posts ({len(sends)} sends)", "WARN")
        R.mark("PASS", f"{len(sends)} sends")
    # plan build ×2 (same brand + month)
    with R.step("INJECT", "2× plan build in parallel"):
        env = dict(os.environ, **WSP.env)
        procs = [subprocess.Popen([sys.executable, "otto_plan.py", "build", "ondaviva", "2026-12"], cwd=str(PLATFORM), env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for _ in range(2)]
        outs = [p.communicate(timeout=120)[0] for p in procs]
        n = len([p for p in posts_of("ondaviva") if p.get("plan") == "2026-12"])
        R.check(sorted(p.returncode for p in procs) == [0, 1], f"exit codes {[p.returncode for p in procs]}")
        R.check(40 <= n <= 80, f"{n} posts for 2026-12 after two parallel builds (one month's worth expected)")
        R.mark("PASS", f"{n} posts, one build refused")
    # growth rollup --send ×2
    with R.step("INJECT", "2× growth --send in parallel"):
        with ap.transaction(sync=False) as dd:
            dd.setdefault("markers", {}).pop("growth_review_sent", None)
        rows, outs, codes = run_pair("growth", "2026-11-01T02:10:00Z", delay="0.5")
        sends = [r for r in rows if r["m"] == "sendMessage"]
        R.check(len(sends) == 1, f"{len(sends)} month-in-review messages from two parallel runs", "WARN")
        R.mark("PASS", f"{len(sends)} sends")
    # ads launch ×2 (money)
    with R.step("INJECT", "2× ads launch in parallel"):
        with ap.transaction(sync=False) as dd:
            for c in dd.get("campaigns", []):
                if c["brand"] == "ondaviva" and c["network"] == "meta" and c["start"] == f"{ym}-01":
                    c["status"] = "approved"; c["remote"] = {}; c.pop("error", None)
                    cid = c["id"]
        rows, outs, codes = run_pair("launch", "2026-10-01T03:00:00Z", brand="ondaviva", delay="0.3", acct={"act_ondaviva": "EUR"})
        camps = [r for r in rows if r["m"] == "POST" and r["path"].endswith("/campaigns")]
        R.check(len(camps) <= 1, f"{len(camps)} Meta campaigns created for ONE approved flight by two parallel launch runs "
                                 f"(double spend; only `flock -n` in crontab prevents it)", "WARN")
        R.mark("PASS", f"campaign creates {len(camps)} · exit {codes}")


def inject_mid_month():
    ap = M["ap"]
    with R.step("INJECT", "mid-month onboarding"):
        # a month nothing else in the simulation plans, built on its 29th (the subprocess's clock: OTTO_SIM_CLOCK)
        sim_now = _real_datetime(2027, 1, 29, 7, 0, tzinfo=timezone.utc)
        code, out, _ = cli("otto_plan.py", "build", "studiolume", "2027-01", env={"OTTO_SIM_CLOCK": sim_now.isoformat()})
        R.check(code == 0, f"plan build exited {code}: {out[-200:]}")
        ps = [p for p in posts_of("studiolume") if p.get("plan") == "2027-01"]
        br = ap.brand(data(), "studiolume")
        past = [p for p in ps if ap.slot_dt(p, br) < sim_now]
        R.check(not past, f"building the current month on the 29th created {len(past)} of {len(ps)} posts with slots already in the past "
                          f"(they can only ever be 'missed')", "WARN")
        R.mark("PASS", f"{len(ps)} posts, {len(past)} in the past")


def perf():
    """Month build against a large data.json (≈ 40 brands × 60 posts)."""
    with R.step("PERF", "large data.json"):
        root = Path(tempfile.mkdtemp(prefix="otto-perf-"))
        d = json.loads((WSP.root / "data.json").read_text())
        base = [p for p in d["posts"] if p["brand"] == "spreebogen"]
        for i in range(40):
            bid = f"clone{i:02d}"
            d["brands"].append(dict(ap_brand(d, "spreebogen"), id=bid, name=f"Clone {i}"))
            for p in base:
                d["posts"].append(dict(p, id=f"c{i:02d}-{p['id'].split('-')[1]}", brand=bid))
        (root / "data.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
        shutil.copy(WSP.root / "index.html", root / "index.html")
        env = {"OTTO_DATA": str(root / "data.json"), "OTTO_HTML": str(root / "index.html")}
        code, out, secs = cli("otto_plan.py", "build", "clone00", "2027-01", env=env)
        size = (root / "data.json").stat().st_size
        R.timings["plan build with 40 brands (" + str(len(d["posts"])) + " posts)"] = secs
        code2, out2, secs2 = cli("ap.py", "decide", f"c01-{base[0]['id'].split('-')[1]}", "approve", env=env)
        R.timings["one ap.py decide (write + fallback sync) at that size"] = secs2
        R.check(code == 0, f"build failed: {out[-200:]}")
        R.check(secs < 10, f"month build took {secs:.1f}s at {len(d['posts'])} posts", "WARN")
        R.mark("PASS", f"{len(d['posts'])} posts · data.json {size // 1024} KB · build {secs:.2f}s · decide {secs2:.2f}s")
        shutil.rmtree(root, ignore_errors=True)


def ap_brand(d, bid):
    return next(b for b in d["brands"] if b["id"] == bid)


# ============================================================================================
# main
# ============================================================================================

def real_repo_fingerprint():
    """path → content hash for everything the engine could write in the real repo (motion/ is covered by the preflight
    check of otto_motion.MOTION — another agent may be working there)."""
    out = {}
    for top in (REPO / "brands", REPO / "demo", PLATFORM / "assets"):
        for p in sorted(top.rglob("*")) if top.exists() else []:
            if p.is_file():
                out[str(p.relative_to(REPO))] = hashlib.sha1(p.read_bytes()).hexdigest()
    for name in ("data.json", ".watch-state.json", "metrics_history.jsonl", ".telegram-state.json", "publish.log", "actions.log",
                 "index.html"):
        f = PLATFORM / name
        if name == "index.html":            # edited by another agent: only the fallback block is ours to guard
            m = re.search(r'<script id="fallback-data" type="application/json">(.*?)</script>', f.read_text(), re.S)
            out["platform/index.html#fallback"] = hashlib.sha1((m.group(1) if m else "").encode()).hexdigest()
        else:
            out["platform/" + name] = hashlib.sha1(f.read_bytes()).hexdigest() if f.exists() else "-"
    return out


def print_matrix(json_path):
    rows = [r for r in R.rows() if r in [b["slug"] for b in BIZ]]
    sym = {"PASS": "ok", "WARN": "WARN", "FAIL": "FAIL", "SKIP": "skip"}
    w = 12
    print("\n" + "business".ljust(16) + "".join(s[:w].ljust(w) for s in STEPS))
    for r in rows:
        line = r.ljust(16)
        for s in STEPS:
            c = R.cells.get((r, s))
            line += (sym[c["status"]] if c else "—").ljust(w)
        print(line)
    other = [(r, s) for (r, s) in R.cells if r not in rows]
    if other:
        print("\nengine / injections / perf:")
        for r, s in other:
            c = R.cells[(r, s)]
            print(f"  {c['status']:4}  {r:7} {s}")
    print("\nnotes (WARN / FAIL / SKIP):")
    for (r, s), c in R.cells.items():
        for n in c["notes"]:
            if not n.startswith("[PASS]"):
                print(f"  {r:14} {s:22} {n.splitlines()[0][:220]}")
    print("\ntimings:")
    for k, v in R.timings.items():
        print(f"  {v:6.2f}s  {k}")
    json_path.write_text(json.dumps({f"{r}|{s}": c for (r, s), c in R.cells.items()} | {"_timings": R.timings}, ensure_ascii=False, indent=1))
    print(f"\nresults → {json_path}")


def main():
    global WSP
    args = sys.argv[1:]
    keep = "--keep" in args
    t_all = time.time()
    fp0 = real_repo_fingerprint()
    root = Path(tempfile.mkdtemp(prefix="otto-sim-"))
    WSP = WS(root).build()
    install_guard()
    load_engine()
    isolation_preflight()
    ym = "2026-10"
    FakeClock.set("2026-09-29T07:00:00Z")
    for b in BIZ:
        step_onboard(b)          # the autopilot skill: brand-add first, then scan
        step_scan(b)
        step_strategy(b)
        step_competitors(b)
        step_plan(b, ym)
        step_copy_and_visuals(b, ym)
        step_compliance(b)
    step_telegram(BIZ)
    step_approvals(BIZ)
    step_publish(BIZ)
    step_ads(BIZ, ym)
    step_insights(BIZ)
    step_ads_report(BIZ)
    step_watch(BIZ)
    step_growth(BIZ)
    step_demo(BIZ)
    step_reels(BIZ)
    inject_bad_sites()
    inject_bad_compliance_json()
    inject_mid_month()
    inject_parallel(ym)
    perf()
    with R.step("ENGINE", "isolation"):
        fp1 = real_repo_fingerprint()
        changed = sorted(k for k in set(fp0) | set(fp1) if fp0.get(k) != fp1.get(k))
        R.check(not changed, f"the REAL repo changed during the simulation: {changed[:8]}")
        html = (PLATFORM / "index.html").read_text()
        R.check(not any(f'"{b["slug"]}"' in html for b in BIZ), "a synthetic brand leaked into the real index.html fallback block")
    R.timings["whole simulation"] = time.time() - t_all
    json_path = Path(args[args.index("--json") + 1]) if "--json" in args else root / "results.json"
    print_matrix(json_path)
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"workspace kept: {root}")
    return 1 if any(c["status"] == "FAIL" for c in R.cells.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
