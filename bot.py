import os
import json
import base64
import requests
from flask import Flask, request

TELEGRAM_TOKEN = "8636414515:AAFnkUylw7VQX4bewPU-0YBnR5icalAMsnE"
GEMINI_KEY = "AIzaSyDrGJXy5MsQ30Nh54GAmmET2WnzaT_ntyA"
TG_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
DB_FILE = "slips.json"

application = Flask(__name__)
app = application

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ocr_image(image_bytes, mime_type="image/jpeg"):
    b64 = base64.b64encode(image_bytes).decode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime_type, "data": b64}},
            {"text": "Extract ALL text from this slip/document exactly as written. Include lighter names, vessel names, escort names, dates, numbers, everything. Output raw text only."}
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048}
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["candidates"][0]["content"]["parts"][0]["text"].strip()

def lev(a, b):
    m, n = len(a), len(b)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            if a[i-1] == b[j-1]: dp[i][j] = dp[i-1][j-1]
            else: dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    return dp[m][n]

def sim(a, b):
    if not a or not b: return 0
    if a == b: return 1.0
    if len(a) < 2 or len(b) < 2: return 0
    if b in a or a in b: return 0.85
    L, S = (a, b) if len(a) >= len(b) else (b, a)
    return (len(L) - lev(L, S)) / len(L)

def search(query, slips):
    q = query.lower().strip()
    qwords = [w for w in q.split() if w]
    results = []
    for slip in slips:
        txt = slip.get("text", "").lower()
        score = 0
        match_type = ""
        if q in txt:
            score = 100; match_type = "exact"
        elif qwords and all(w in txt for w in qwords):
            score = 90; match_type = "exact"
        else:
            matched = [w for w in qwords if len(w) > 1 and w in txt]
            if matched:
                score = int(len(matched)/len(qwords)*70); match_type = "partial"
            else:
                twords = txt.split()
                best = 0
                for qw in qwords:
                    if len(qw) < 2: continue
                    for tw in twords:
                        v = sim(qw, tw)
                        if v > best: best = v
                if best >= 0.6:
                    score = int(best*50); match_type = "fuzzy"
        if score > 0:
            results.append((score, match_type, slip))
    results.sort(key=lambda x: -x[0])
    return results

def send_msg(chat_id, text):
    requests.post(f"{TG_URL}/sendMessage", json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML"
    }, timeout=10)

def send_typing(chat_id):
    requests.post(f"{TG_URL}/sendChatAction", json={
        "chat_id": chat_id, "action": "typing"
    }, timeout=5)

def get_file_bytes(file_id):
    r = requests.get(f"{TG_URL}/getFile", params={"file_id": file_id}, timeout=10)
    fp = r.json()["result"]["file_path"]
    r2 = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{fp}", timeout=30)
    return r2.content

@application.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data: return "ok"
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    photo = msg.get("photo")
    document = msg.get("document")
    if not chat_id: return "ok"
    slips = load_db()

    if photo:
        send_typing(chat_id)
        send_msg(chat_id, "⏳ ছবি পড়ছি, একটু অপেক্ষা করুন...")
        try:
            file_id = photo[-1]["file_id"]
            img_bytes = get_file_bytes(file_id)
            ocr_text = ocr_image(img_bytes)
            slip = {"id": len(slips)+1, "file_id": file_id, "text": ocr_text}
            slips.append(slip)
            save_db(slips)
            send_msg(chat_id,
                f"✅ <b>স্লিপ #{slip['id']} সেভ হয়েছে!</b>\n\n"
                f"📝 পাওয়া লেখা:\n{ocr_text[:400]}\n\n"
                f"মোট স্লিপ: {len(slips)}টি"
            )
        except Exception as e:
            send_msg(chat_id, f"❌ সমস্যা হয়েছে: {str(e)[:150]}")
        return "ok"

    if document and document.get("mime_type","").startswith("image/"):
        send_typing(chat_id)
        send_msg(chat_id, "⏳ ছবি পড়ছি...")
        try:
            file_id = document["file_id"]
            mime = document.get("mime_type","image/jpeg")
            img_bytes = get_file_bytes(file_id)
            ocr_text = ocr_image(img_bytes, mime)
            slip = {"id": len(slips)+1, "file_id": file_id, "text": ocr_text}
            slips.append(slip)
            save_db(slips)
            send_msg(chat_id,
                f"✅ <b>স্লিপ #{slip['id']} সেভ!</b>\n\n"
                f"📝 {ocr_text[:400]}\n\nমোট: {len(slips)}টি"
            )
        except Exception as e:
            send_msg(chat_id, f"❌ সমস্যা: {str(e)[:150]}")
        return "ok"

    if text:
        if text.startswith("/start") or text.startswith("/help"):
            send_msg(chat_id,
                "🔍 <b>স্লিপ সার্চ Bot</b>\n\n"
                "📌 <b>ব্যবহার:</b>\n"
                "1️⃣ স্লিপের ছবি পাঠান → সেভ হবে\n"
                "2️⃣ নাম লিখুন → খুঁজে দেবে\n\n"
                "✅ বাংলা বা ইংরেজি দুটোতেই কাজ করে\n"
                "✅ বানান ভুল হলেও খুঁজবে\n\n"
                "/count — মোট স্লিপ\n"
                "/list — সব স্লিপ\n"
                "/clear — সব মুছুন"
            )
        elif text.startswith("/count"):
            send_msg(chat_id, f"📊 মোট স্লিপ: <b>{len(slips)}টি</b>")
        elif text.startswith("/list"):
            if not slips:
                send_msg(chat_id, "📂 কোনো স্লিপ নেই।")
            else:
                lines = [f"📋 <b>মোট {len(slips)}টি স্লিপ:</b>\n"]
                for s in slips[-20:]:
                    preview = s["text"][:60].replace("\n"," ")
                    lines.append(f"#{s['id']}: {preview}...")
                send_msg(chat_id, "\n".join(lines))
        elif text.startswith("/clear"):
            save_db([])
            send_msg(chat_id, "🗑️ সব স্লিপ মুছে ফেলা হয়েছে।")
        elif text.startswith("/"):
            send_msg(chat_id, "❓ /help লিখুন।")
        else:
            if not slips:
                send_msg(chat_id, "📂 এখনো কোনো স্লিপ নেই।\nআগে স্লিপের ছবি পাঠান।")
                return "ok"
            send_typing(chat_id)
            results = search(text, slips)
            if not results:
                send_msg(chat_id, f"🔍 '<b>{text}</b>' পাওয়া যায়নি।\nভিন্ন বানান বা ছোট শব্দ দিয়ে চেষ্টা করুন।")
            else:
                mt_label = {"exact":"✅ পুরো মিল","partial":"🔶 আংশিক","fuzzy":"🔸 কাছাকাছি"}
                lines = [f"🔍 '<b>{text}</b>' — {len(results)}টি পাওয়া গেছে:\n"]
                for score, mt, slip in results[:5]:
                    label = mt_label.get(mt,"")
                    preview = slip["text"][:250].replace("\n"," | ")
                    lines.append(f"━━━━━━━━\n{label} — স্লিপ #{slip['id']}\n{preview}\n")
                if len(results) > 5:
                    lines.append(f"\n... আরো {len(results)-5}টি আছে।")
                send_msg(chat_id, "\n".join(lines))
    return "ok"

@application.route("/", methods=["GET"])
def index():
    return "Slip Search Bot চলছে! ✅"

@application.route("/set_webhook", methods=["GET"])
def set_webhook():
    url = request.args.get("url","")
    if not url: return "url দিন"
    r = requests.get(f"{TG_URL}/setWebhook", params={"url": f"{url}/webhook"})
    return str(r.json())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    application.run(host="0.0.0.0", port=port)
