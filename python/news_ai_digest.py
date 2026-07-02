import os
import sys
import json
import base64
import re
import time
from datetime import datetime
from email.mime.text import MIMEText
import requests
import xml.etree.ElementTree as ET
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

sys.stdout.reconfigure(encoding="utf-8")

# === CONFIGURAZIONE ===

SITI_NEWS = [
    {"nome": "Wired Italia", "url": "https://www.wired.it"},
    {"nome": "Tom's Hardware Italia", "url": "https://www.tomshw.it"},
    {"nome": "HDBlog", "url": "https://www.hdblog.it/innovazione/"},
    {"nome": "Punto Informatico", "url": "https://www.punto-informatico.it"},
    {"nome": "Everyeye Tech", "url": "https://www.everyeye.it/tech/"},
    {"nome": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence"},
    {"nome": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/"},
    {"nome": "Ars Technica AI", "url": "https://arstechnica.com/ai/"},
    {"nome": "VentureBeat AI", "url": "https://venturebeat.com/ai/"},
    {"nome": "OpenAI Blog", "url": "https://openai.com/news/"},
]

YOUTUBER_CHANNELS = {
    "RaffaeleGaito": "UCrebGs3b-Z7JLKQM2YOpUKA",
    "simone_rizzo98": "UCbMlkb79E12CwveGAtdFj-A",
    "AntonioGuadagnoAI": "UCAFhdtRnKRqJQI7ht1Puo9Q",
    "giovannibeggiato": "UCQbrJm-05Er6plcuNoVhuOw",
    "gcastagna": "UCFermqARa66pnGJVV1PnYGA",
    "gabrysolution": "UC8oBIE88TrCD1b-gnVqXzgw",
    "GiulioMichelon": "UCwkM5ziXQsnI422lEwZViwg",
    "aclasio": "UCoZx0L3xyfhmSr0Vabu4G_g",
    "lorenzodelia125": "UCA8V_dXrkT8DbuCCARrNzcQ",
    "VantaggioArtificiale": "UChBdbETbc6tcveqbKtIMG_w",
}

MODELLI_GEMINI = [
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-latest",
]

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


# === YOUTUBE RSS ===

def get_video_recenti(handle, channel_id):
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        r = requests.get(feed_url, timeout=15)
        root = ET.fromstring(r.content)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
        }
        risultati = []
        for entry in root.findall("atom:entry", ns)[:2]:
            titolo = entry.find("atom:title", ns).text or ""
            link = entry.find("atom:link", ns).attrib.get("href", "")
            desc_el = entry.find(".//media:description", ns)
            descrizione = (desc_el.text or "")[:600] if desc_el is not None else ""
            pub_el = entry.find("atom:published", ns)
            data_pub = ""
            if pub_el is not None and pub_el.text:
                try:
                    dt = datetime.fromisoformat(pub_el.text.replace("Z", "+00:00"))
                    data_pub = dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
            risultati.append({
                "fonte": f"YouTube @{handle}",
                "titolo": titolo,
                "contenuto": descrizione,
                "url": link,
                "data": data_pub,
            })
        print(f"  YouTube @{handle}: {len(risultati)} video trovati")
        return risultati
    except Exception as e:
        print(f"  Errore RSS @{handle}: {e}")
        return []


# === FIRECRAWL ===

def scrapa_sito(sito):
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"url": sito["url"], "formats": ["markdown"], "onlyMainContent": True},
            timeout=30,
        )
        data = r.json()
        if data.get("success"):
            testo = data.get("data", {}).get("markdown", "")[:1500]
            print(f"  Firecrawl OK: {sito['nome']} ({len(testo)} chars)")
            return {"fonte": sito["nome"], "url": sito["url"], "contenuto": testo}
    except Exception as e:
        print(f"  Errore Firecrawl {sito['nome']}: {e}")
    return None


# === GEMINI ===

def seleziona_top10_gemini(contenuti):
    blocchi = []
    for c in contenuti:
        blocchi.append(
            f"=== FONTE: {c['fonte']} ===\nURL: {c['url']}\nDATA: {c.get('data','')}\n{c['contenuto']}"
        )

    prompt = (
        "Sei l'assistente personale di Gabriele, appassionato di AI, nuovi tool e tecnologia.\n"
        "Analizza tutti i contenuti seguenti (articoli di siti tech e video YouTube italiani) "
        "e seleziona le TOP 10 notizie piu interessanti e rilevanti su: AI, nuovi tool, nuove app, skill digitali, automazioni, LLM.\n\n"
        "IGNORA: notizie di politica, sport, gossip, hardware gaming non AI, notizie duplicate.\n"
        "PRIORITA: AI generativa, nuovi modelli LLM, tool pratici per produttivita, automazioni, notizie pratiche e utili.\n\n"
        "Per ogni notizia usa ESATTAMENTE questo formato (niente altro):\n\n"
        "- TITOLO: [titolo chiaro in italiano]\n"
        "- FONTE: [nome della fonte]\n"
        "- LINK: [URL originale completo]\n"
        "- DATA: [data di pubblicazione nel formato GG/MM/AAAA, o lascia vuoto se non disponibile]\n"
        "- RIASSUNTO: [3-4 righe in italiano semplice, come se lo spiegassi a un amico non tecnico]\n\n"
        "Separa ogni notizia con una riga che contiene solo: ---\n\n"
        "Seleziona esattamente 10 notizie (o meno se i contenuti rilevanti sono insufficienti).\n\n"
        + "\n\n".join(blocchi)
    )

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for modello in MODELLI_GEMINI:
        url = (
            "https://generativelanguage.googleapis.com/v1/models/"
            + modello
            + ":generateContent?key="
            + GEMINI_API_KEY
        )
        try:
            r = requests.post(url, json=payload, timeout=120)
            print(f"Gemini {modello} status: {r.status_code}")
            risposta = r.json()
            if r.status_code != 200:
                print(f"Gemini errore API: {risposta}")
                time.sleep(2)
                continue
            testo = (
                risposta
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            if testo:
                print(f"Gemini OK ({modello})")
                return testo
            print(f"Gemini risposta vuota: {risposta}")
        except Exception as e:
            print(f"Gemini errore {modello}: {e}")
            time.sleep(2)

    return None


# === PARSING ===

def parse_notizie(testo):
    notizie = []
    for blocco in testo.strip().split("---"):
        if not blocco.strip():
            continue
        n = {}
        righe_riassunto = []
        in_riassunto = False
        for riga in blocco.strip().splitlines():
            riga = riga.strip()
            if riga.startswith("- TITOLO:"):
                n["titolo"] = riga.replace("- TITOLO:", "").strip()
                in_riassunto = False
            elif riga.startswith("- FONTE:"):
                n["fonte"] = riga.replace("- FONTE:", "").strip()
                in_riassunto = False
            elif riga.startswith("- LINK:"):
                n["link"] = riga.replace("- LINK:", "").strip()
                in_riassunto = False
            elif riga.startswith("- DATA:"):
                n["data"] = riga.replace("- DATA:", "").strip()
                in_riassunto = False
            elif riga.startswith("- RIASSUNTO:"):
                righe_riassunto = [riga.replace("- RIASSUNTO:", "").strip()]
                in_riassunto = True
            elif in_riassunto and riga:
                righe_riassunto.append(riga)
        if righe_riassunto:
            n["riassunto"] = " ".join(righe_riassunto)
        if n.get("titolo") and n.get("riassunto"):
            notizie.append(n)
    return notizie[:10]


# === SALVATAGGIO JSON ===

def salva_json(notizie):
    oggi = datetime.now().strftime("%Y-%m-%d")
    cartella = "data/news"
    os.makedirs(cartella, exist_ok=True)
    percorso = f"{cartella}/{oggi}.json"
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump({"data": oggi, "notizie": notizie}, f, ensure_ascii=False, indent=2)
    print(f"JSON salvato: {percorso}")


# === PAGINA HTML SITO ===

def genera_html_archivio():
    cartella = "data/news"
    file_json = sorted(
        [f for f in os.listdir(cartella) if f.endswith(".json")], reverse=True
    )
    archivio = []
    for nome_file in file_json:
        with open(f"{cartella}/{nome_file}", encoding="utf-8") as f:
            archivio.append(json.load(f))

    options_html = ""
    for entry in archivio:
        data_fmt = datetime.strptime(entry["data"], "%Y-%m-%d").strftime("%d/%m/%Y")
        options_html += f'<option value="{entry["data"]}">{data_fmt}</option>\n'

    giorni_html = ""
    for entry in archivio:
        notizie_html = ""
        for n in entry["notizie"]:
            link = n.get("link", "#")
            notizie_html += f"""
<div class="notizia">
  <div class="notizia-fonte">{n.get("fonte","")}{(" &bull; " + n["data"]) if n.get("data") else ""}</div>
  <div class="notizia-titolo">{n.get("titolo","")}</div>
  <div class="notizia-riassunto">{n.get("riassunto","")}</div>
  <a href="{link}" target="_blank" rel="noopener" class="notizia-link">Leggi l'articolo completo &rarr;</a>
</div>"""
        giorni_html += f'<div class="giorno" data-date="{entry["data"]}">{notizie_html}</div>\n'

    oggi = archivio[0]["data"] if archivio else ""

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI News del Giorno</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Poppins,sans-serif;background:#FBF2EB;color:#292929;min-height:100vh}}
.header{{background:linear-gradient(135deg,#7B5FC8,#5A3FA8);color:white;padding:40px 24px;text-align:center}}
.header h1{{font-size:28px;font-weight:700;margin-bottom:8px}}
.header p{{font-size:15px;opacity:.85}}
.container{{max-width:760px;margin:0 auto;padding:32px 16px}}
.selettore{{background:white;border-radius:16px;border:2px solid #E8E4D9;padding:20px 24px;margin-bottom:28px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;box-shadow:0 0 12px #E8E8E8}}
.selettore label{{font-weight:600;font-size:14px;color:#4D4D4D}}
select{{border:1.5px solid #C4B3E8;border-radius:9999px;padding:8px 20px;font-family:Poppins,sans-serif;font-size:14px;color:#292929;background:white;cursor:pointer;outline:none}}
select:focus{{border-color:#7B5FC8}}
.giorno{{display:none}}
.giorno.attivo{{display:block}}
.notizia{{background:white;border-radius:20px;border:2px solid #E8E4D9;padding:24px;margin-bottom:16px;box-shadow:0 0 12px #E8E8E8}}
.notizia-fonte{{font-size:11px;font-weight:700;color:#7B5FC8;text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px}}
.notizia-titolo{{font-size:17px;font-weight:700;color:#292929;margin-bottom:12px;line-height:1.4}}
.notizia-riassunto{{font-size:14px;color:#4D4D4D;line-height:1.75;margin-bottom:16px}}
.notizia-link{{display:inline-block;background:#7B5FC8;color:white;border-radius:9999px;padding:8px 20px;font-size:13px;font-weight:600;text-decoration:none;transition:background .2s}}
.notizia-link:hover{{background:#5A3FA8}}
.footer{{text-align:center;padding:32px;color:#4D4D4D;font-size:13px}}
</style>
</head>
<body>
<div class="header">
  <h1>AI News del Giorno</h1>
  <p>Le 10 notizie piu importanti su AI, tool e tecnologia &mdash; selezionate da Gemini ogni giorno alle 18:00</p>
</div>
<div class="container">
  <div class="selettore">
    <label>Archivio date:</label>
    <select id="sel" onchange="mostra(this.value)">
      {options_html}
    </select>
  </div>
  {giorni_html}
</div>
<div class="footer">Aggiornato automaticamente ogni giorno alle 18:00 &bull; Powered by Gemini AI + Firecrawl</div>
<script>
function mostra(d){{
  document.querySelectorAll('.giorno').forEach(g=>g.classList.remove('attivo'));
  var el=document.querySelector('.giorno[data-date="'+d+'"]');
  if(el)el.classList.add('attivo');
}}
mostra('{oggi}');
</script>
</body>
</html>"""

    with open("news-ai.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("sito/news-ai.html aggiornato")


# === EMAIL ===

def get_credentials():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(Request())
    return creds

def notizie_in_html_email(notizie):
    righe = []
    for n in notizie:
        righe.append(
            f'<div style="margin-bottom:20px;padding:16px;background:#fff;border-radius:12px;border:1px solid #E8E4D9;">'
            f'<div style="font-size:11px;font-weight:700;color:#7B5FC8;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px;">{n.get("fonte","")}</div>'
            f'<div style="font-size:16px;font-weight:700;color:#292929;margin-bottom:10px;">{n.get("titolo","")}</div>'
            f'<div style="font-size:14px;color:#4D4D4D;line-height:1.7;margin-bottom:12px;">{n.get("riassunto","")}</div>'
            f'<a href="{n.get("link","#")}" style="display:inline-block;background:#7B5FC8;color:white;border-radius:9999px;padding:7px 18px;font-size:13px;font-weight:600;text-decoration:none;">Leggi l\'articolo &rarr;</a>'
            f'</div>'
        )
    return "".join(righe)

def invia_email(service, notizie):
    oggi = datetime.now().strftime("%d/%m/%Y")
    oggetto = f"AI News del {oggi} — TOP {len(notizie)}"
    corpo_html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;max-width:640px;margin:0 auto;">
<div style="background:linear-gradient(135deg,#7B5FC8,#5A3FA8);color:white;padding:28px 24px;border-radius:12px 12px 0 0;text-align:center;">
  <h1 style="font-size:22px;margin:0 0 6px;">AI News del {oggi}</h1>
  <p style="margin:0;opacity:.85;font-size:14px;">Le {len(notizie)} notizie piu importanti su AI, tool e tecnologia</p>
</div>
<div style="padding:24px 0;">
{notizie_in_html_email(notizie)}
</div>
<div style="text-align:center;padding:16px;color:#999;font-size:12px;border-top:1px solid #eee;">
Generato automaticamente da Gemini AI + Firecrawl
</div>
</div>"""

    message = MIMEText(corpo_html, "html")
    message["to"] = "gabrimarche@gmail.com"
    message["from"] = "gabrimarche@gmail.com"
    message["subject"] = oggetto
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Email inviata: {oggetto}")


# === MAIN ===

def main():
    print("=== AI News Digest ===")
    print(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 1. Raccolta contenuti
    contenuti = []

    print("\nScraping siti news con Firecrawl...")
    for sito in SITI_NEWS:
        risultato = scrapa_sito(sito)
        if risultato:
            contenuti.append(risultato)
        time.sleep(1)

    print("\nRecupero video YouTube via RSS...")
    for handle, channel_id in YOUTUBER_CHANNELS.items():
        video = get_video_recenti(handle, channel_id)
        contenuti.extend(video)
        time.sleep(0.5)

    print(f"\nTotale contenuti raccolti: {len(contenuti)}")

    if not contenuti:
        print("Nessun contenuto raccolto. Uscita.")
        return

    # 2. Selezione TOP 10 con Gemini
    print("\nSelezione TOP 10 con Gemini...")
    testo_gemini = seleziona_top10_gemini(contenuti)
    if not testo_gemini:
        print("Gemini non disponibile. Uscita.")
        return

    notizie = parse_notizie(testo_gemini)
    print(f"Notizie selezionate: {len(notizie)}")

    # 3. Salva JSON
    salva_json(notizie)

    # 4. Aggiorna pagina sito
    genera_html_archivio()

    print("\n=== COMPLETATO ===")


if __name__ == "__main__":
    main()

