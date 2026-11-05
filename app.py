"""NutriAI beta: un solo backend para Web + WhatsApp + Instagram (3 niveles de atención)."""
import os, re, json, base64, sqlite3, threading, datetime
import requests
import planificador
from flask import Flask, request, jsonify, render_template, render_template_string, session
from dotenv import load_dotenv
load_dotenv()
E = os.environ.get
GEMINI_KEY, MODEL = E("GEMINI_API_KEY"), E("GEMINI_MODEL", "gemini-2.5-flash")
VERIFY, PANEL_PASS = E("VERIFY_TOKEN", "nutriai_verify"), E("PANEL_PASSWORD", "nutri123")
WA_TOKEN, WA_PHONE_ID, IG_TOKEN = E("WA_TOKEN"), E("WA_PHONE_ID"), E("IG_TOKEN")
GRAPH = "https://graph.facebook.com/v21.0"
IG_HOST = E("IG_HOST", GRAPH)  # con token de "Instagram Login" usa https://graph.instagram.com/v21.0
app = Flask(__name__); app.secret_key = E("SECRET_KEY", "cambia-esto")

# ---------- base de datos (SQLite, gratis) ----------
def db():
    c = sqlite3.connect("nutriai.db", timeout=10); c.row_factory = sqlite3.Row; return c
with db() as c:
    c.executescript("""
    create table if not exists users(key text primary key, mode text default 'bot', fails int default 0, state text default '');
    create table if not exists tickets(id integer primary key autoincrement, key text, level int, category text, summary text, contact text default '', status text default 'abierto', created text default current_timestamp);
    create table if not exists msgs(id integer primary key autoincrement, key text, who text, text text, ts text default current_timestamp);
    create table if not exists planes(key text primary key, data text);""")
def user(key):
    with db() as c:
        c.execute("insert or ignore into users(key) values(?)", (key,))
        return dict(c.execute("select * from users where key=?", (key,)).fetchone())
def upd(key, **kw):
    with db() as c: c.execute(f"update users set {','.join(k+'=?' for k in kw)} where key=?", (*kw.values(), key))
def log(key, who, text):
    with db() as c: c.execute("insert into msgs(key,who,text) values(?,?,?)", (key, who, text or ""))

# ---------- Gemini (capa gratuita de Google AI Studio) ----------
def gemini(parts, system=None, as_json=False):
    body = {"contents": [{"role": "user", "parts": parts}]}
    if system: body["systemInstruction"] = {"parts": [{"text": system}]}
    if as_json: body["generationConfig"] = {"responseMimeType": "application/json"}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                      params={"key": GEMINI_KEY}, json=body, timeout=60)
    r.raise_for_status()
    return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])

KB = """NutriAI: plataforma donde fotografías tu platillo o tus ingredientes. Con platillo: calorías, proteínas, carbohidratos, grasas, fibra y un semáforo (qué sumar y qué evitar hoy). Con ingredientes: recetas con lo que tienes, tiempo de preparación y cuánto tiempo les queda a los ingredientes.
Registro también por código de barras, voz o texto. Hecha para foráneos y jóvenes, deportistas, condiciones especiales y control de peso.
Planes: Básico GRATIS (registro diario, conteo de calorías, alertas esenciales). Pro Individual $9.99 USD/mes (antes $14.99; primer mes gratis; fotos ilimitadas, alertas médicas urgentes, recetario inteligente, métricas avanzadas). Familiar $16.99 USD/mes (hasta 5 cuentas, listas de compras sincronizadas, menú semanal automatizado).
Reto de 7 días y quiz gratis en redes y web: www.nutriai.mx. Validado por un comité técnico de nutriólogos, con verificación cruzada de alérgenos."""
FAQ_SYS = ("Eres Dr. Nutri 🦦, el doctor de bolsillo de NutriAI. Español, cercano, máximo 4 líneas. Responde SOLO con esta información; "
           "puedes dar tips generales de alimentación (nunca médicos ni diagnósticos).\n" + KB +
           "\nSi no puedes responder con eso, responde exactamente: NO_SE")
SCAN_SYS = """Eres Dr. Nutri. Analiza la foto y responde SOLO JSON con esta forma:
{"tipo":"platillo|ingredientes|otro","titulo":"","calorias":0,"proteina_g":0,"carbohidratos_g":0,"grasas_g":0,"fibra_g":0,"semaforo":"verde|amarillo|rojo","consejo":"max 2 frases",
"ingredientes":[{"nombre":"","vida_util":"ej. 3-5 días en refri"}],"recetas":[{"nombre":"","tiempo_min":0,"calorias":0,"pasos":["",""]}]}
Reglas: platillo = macros totales estimados de lo que se ve, ingredientes y recetas vacíos. ingredientes = calorias/macros en 0, lista cada ingrediente visible con su vida útil estimada y 3 recetas rápidas SOLO con lo visible (+ básicos de despensa). Si no es comida: tipo otro y consejo amable. Son estimaciones; no diagnostiques."""

def scan(img_bytes, mime="image/jpeg"):
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(img_bytes).decode()}}, {"text": "Analiza esta foto."}]
    return json.loads(re.sub(r"^```(json)?|```$", "", gemini(parts, SCAN_SYS, True).strip()))
SEM = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
def fmt(d):
    if d.get("tipo") == "otro": return "🦦 " + d.get("consejo", "No veo comida en la foto, ¡mándame otra!")
    o = [f"🦦 *{d.get('titulo', 'Tu comida')}*"]
    if d.get("calorias"): o.append(f"🔥 {d['calorias']} kcal | 💪 {d.get('proteina_g',0)} g proteína | 🍞 {d.get('carbohidratos_g',0)} g carbs | 🥑 {d.get('grasas_g',0)} g grasa | 🌾 {d.get('fibra_g',0)} g fibra")
    o.append(f"{SEM.get(d.get('semaforo'), '')} {d.get('consejo', '')}")
    if d.get("ingredientes"): o.append("⏳ *Cuánto les queda:*\n" + "\n".join(f"• {i['nombre']}: {i['vida_util']}" for i in d["ingredientes"]))
    for r in d.get("recetas", []): o.append(f"🍳 *{r['nombre']}* ({r['tiempo_min']} min)\n" + "\n".join(f"{n}. {p}" for n, p in enumerate(r["pasos"], 1)))
    o.append("_Estimación orientativa, no sustituye a un profesional de la salud._")
    return "\n\n".join(o)

# ---------- cerebro de 3 niveles ----------
WELCOME = ("¡Hola! Soy Dr. Nutri 🦦, tu doctor de bolsillo.\n\n1️⃣ Analizar mi platillo o ingredientes (mándame una foto 📸)\n2️⃣ Planes y precios\n"
           "3️⃣ Hablar con un asesor (edades, quién puede usarla, dudas)\n4️⃣ Pagos, quejas o sugerencias\n5️⃣ Planear mi quincena con mi presupuesto 🛒\n\nO escríbeme tu pregunta.")
PLANES = ("💙 *Planes NutriAI*\n• Básico: GRATIS (registro diario, calorías, alertas esenciales)\n• Pro Individual: $9.99 USD/mes, primer mes gratis (fotos ilimitadas, alertas médicas, recetario inteligente, métricas)\n"
          "• Familiar: $16.99 USD/mes (hasta 5 cuentas, listas de compras y menú semanal)\n\n¿Quieres que te pase con un asesor? Escribe 3.")
PLANES_TXT = PLANES
SALUDOS = {"hola", "menu", "menú", "inicio", "hi", "buenas", "buenos dias", "buenas tardes", "start"}
L3 = re.compile(r"cobr|\bcargos?\b|reembols|devol|factura|queja|sugerencia|cancel|problema.*pago|pago.*(fall|rechaz|duplic|error)|error.*pago|tarjeta.*(rechaz|fall)", re.I)
L2 = re.compile(r"edad|años|menor de|niñ|adolescente|embaraz|lactan|diabet|hipertens|al[eé]rg|intoleran|cel[ií]ac|enfermedad|m[eé]dic|qui[eé]n(es)? puede|puedo usar", re.I)
HUMAN = re.compile(r"asesor|humano|agente|operador|hablar con alguien", re.I)

def en_horario():  # L-V 9 a 18 h, hora CDMX (UTC-6)
    n = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)
    return n.weekday() < 5 and 9 <= n.hour < 18

def escalate(key, lvl, text):
    cat = "Consulta de asesor" if lvl == 2 else "Pagos / quejas / sugerencias"
    with db() as c: c.execute("insert into tickets(key,level,category,summary) values(?,?,?,?)", (key, lvl, cat, text[:500]))
    upd(key, mode="asesor" if lvl == 2 else "callcenter", fails=0, state="contact" if key.startswith("web:") else "")
    quien = "un asesor" if lvl == 2 else "nuestro equipo de atención a clientes"
    m = f"Te paso con {quien} 🦦 y ya le comparto lo que me contaste, para que no repitas nada."
    m += " Te responde en breve." if en_horario() else " Ahora estamos fuera de horario (L-V 9:00 a 18:00, hora CDMX): tu caso quedó registrado y te respondemos en cuanto abramos."
    if key.startswith("web:"): m += "\nDéjame tu WhatsApp o correo en el siguiente mensaje."
    return m + "\n(Escribe *bot* para volver conmigo.)"

# ---------- planificador de quincena (presupuesto -> compras y porciones) ----------
def _num(t):
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    m = re.search(r"\d+(?:[.,]\d+)?", t)
    return float(m.group().replace(",", ".")) if m else None
def _rango(lo, hi):
    return lambda t: (lambda v: v if v is not None and lo <= v <= hi else None)(_num(t))
def _opcion(*validos):
    return lambda t: (lambda v: int(v) if v in validos else None)(_num(t))
def _sexo(t):
    n = norm(t).strip()
    return "h" if n[:1] == "h" or "hombre" in n else "m" if n[:1] == "m" or "mujer" in n else None
def _kcal(t):
    if re.search(r"\bno\b|ni idea|nose|no se", norm(t)) and _num(t) is None: return 0
    return _rango(500, 6000)(t)
PLAN_PASOS = [
    ("presupuesto", "💰 ¿Cuánto dinero tienes para tu *quincena de comida*? (solo el número en pesos, ej. 800)", _rango(100, 20000)),
    ("peso", "⚖️ ¿Cuánto pesas? (en kg)", _rango(30, 250)),
    ("estatura", "📏 ¿Cuánto mides? (en cm, ej. 170)", _rango(120, 230)),
    ("edad", "🎂 ¿Qué edad tienes?", _rango(10, 90)),
    ("sexo", "¿Eres hombre o mujer? (escribe *h* o *m*; solo lo uso para calcular tus calorías)", _sexo),
    ("actividad", "🏋️ Tu actividad:\n1️⃣ Casi no me muevo\n2️⃣ Entreno 2-3 veces por semana\n3️⃣ Entreno 4 o más veces", _opcion(1, 2, 3)),
    ("objetivo", "🎯 Tu objetivo:\n1️⃣ Mantener mi peso\n2️⃣ Bajar grasa\n3️⃣ Ganar músculo", _opcion(1, 2, 3)),
    ("comidas", "🍽️ ¿Cuántas comidas haces al día? (escribe 3 o 4)", _opcion(3, 4)),
    ("kcal", "🔥 ¿Cuántas calorías crees que comes al día ahora? Si no sabes, escribe *no sé* y calculo lo que necesitas.", _kcal),
]
def plan_inicio(key):
    upd(key, state="plan:0:{}")
    return ["🛒 ¡Vamos a armar tu quincena! Son 9 preguntas rápidas (escribe *cancelar* para salir).\n\n" + PLAN_PASOS[0][1]]
def plan_guardar(key, p):
    with db() as c: c.execute("insert or replace into planes(key,data) values(?,?)", (key, json.dumps(p)))
def plan_cargar(key):
    with db() as c: r = c.execute("select data from planes where key=?", (key,)).fetchone()
    return json.loads(r["data"]) if r else None
def plan_step(key, u, t):
    _, paso, datos = u["state"].split(":", 2); i = int(paso); datos = json.loads(datos)
    nombre, pregunta, parser = PLAN_PASOS[i]
    val = parser(t)
    if val is None: return ["No te entendí 🤔 " + pregunta]
    datos[nombre] = val
    if nombre == "edad" and val < 15:
        upd(key, state=""); return ["Este planificador es para mayores de 15 años 💙 Escribe *3* para hablar con un asesor."]
    if i + 1 < len(PLAN_PASOS):
        upd(key, state=f"plan:{i+1}:{json.dumps(datos)}"); return [PLAN_PASOS[i + 1][1]]
    upd(key, state="")
    try: p = planificador.armar(datos)
    except ValueError as e: return [f"No pude armar el plan: {e} Escribe *plan* para intentarlo de nuevo."]
    except Exception as e: print("plan error", e); return ["No pude armar el plan 😅 Escribe *plan* para intentarlo de nuevo."]
    plan_guardar(key, p); return [planificador.texto_chat(p)]
def plan_comando(key, low):
    p = plan_cargar(key)
    if not p: return ["Primero armamos tu plan 🛒 Escribe *plan* y te hago unas preguntas."]
    if low == "menu15": return [planificador.texto_menu(p)]
    if low == "lista": return [planificador.texto_lista(p)]
    if low == "mi plan": return [planificador.texto_chat(p)]
    if GEMINI_KEY:
        try: return ["🍳 *Recetas con tus ingredientes*\n\n" + gemini([{"text": planificador.prompt_recetas(p)}]).strip()]
        except Exception as e: print("recetas error", e)
    return ["Ahora no pude conectar con la IA para las recetas 😅 Aquí tienes tu menú completo:\n\n" + planificador.texto_menu(p)]
PLAN_TRIGGER = re.compile(r"quincena|presupuesto|despensa|lista de compras|plan de comidas|armar.*(plan|menu)|planear.*(comida|semana|quincena)")

def handle(ch, uid, text=None, image=None):
    """Devuelve lista de respuestas. Lista vacía = lo atiende un humano desde el panel."""
    key = f"{ch}:{uid}"; u = user(key); t = (text or "").strip(); low = t.lower()
    log(key, "user", t or "[foto]")
    if u["mode"] != "bot":
        if low in ("bot", "menu", "menú", "volver"): upd(key, mode="bot", fails=0, state=""); return [WELCOME]
        if u["state"] == "contact" and t:
            with db() as c: c.execute("update tickets set contact=? where key=? and status='abierto'", (t[:100], key))
            upd(key, state=""); return ["¡Anotado! ✅ Te contactarán por ahí."]
        return []
    if u["state"].startswith("plan:"):
        if low in ("cancelar", "salir", "menu", "menú", "inicio", "hola"): upd(key, state=""); return [WELCOME]
        return plan_step(key, u, t)
    if image:
        try: return [fmt(scan(*image))]
        except Exception as e: print("scan error", e); return ["No pude analizar la foto 😅 Prueba con más luz y que se vea bien el plato o los ingredientes."]
    if low in SALUDOS or not t: return [WELCOME]
    if low == "1": return ["¡Listo! 📸 Mándame una foto de tu platillo (calorías y macros) o de tus ingredientes (qué cocinar y cuánto tiempo les queda)."]
    if low == "2": return [PLANES]
    if low == "3": return [escalate(key, 2, "El cliente pidió un asesor")]
    if low == "4": return [escalate(key, 3, "El cliente pidió ayuda con pagos/queja/sugerencia")]
    if low in ("5", "plan", "planear") or PLAN_TRIGGER.search(norm(t)): return plan_inicio(key)
    if low in ("recetas", "menu15", "lista", "mi plan"): return plan_comando(key, low)
    if L3.search(t): return [escalate(key, 3, t)]
    if L2.search(t) or HUMAN.search(t): return [escalate(key, 2, t)]
    ans = faq_local(t)
    if not ans and GEMINI_KEY:
        try: ans = gemini([{"text": t}], FAQ_SYS).strip()
        except Exception as e: print("faq error", e); ans = "NO_SE"
    if not ans or "NO_SE" in ans:
        f = u["fails"] + 1; upd(key, fails=f)
        if f >= 2: return [escalate(key, 2, "El bot no entendió dos veces. Último mensaje: " + t)]
        return ["No tengo una respuesta segura para eso 🤔 Puedes escribirlo de otra forma, o escribe *3* para hablar con un asesor.\n\n1️⃣ Analizar foto  2️⃣ Planes  3️⃣ Asesor  4️⃣ Pagos/quejas  5️⃣ Plan de quincena"]
    upd(key, fails=0); return [ans]

# ---------- Nivel 1 automático SIN IA (funciona aunque Gemini falle) ----------
import unicodedata
def norm(t): return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
FAQ_RULES = [
 (r"cuanto cuesta|precio|costo|planes?\b|gratis|suscrip|mensualidad|\bpro\b|familiar", PLANES_TXT),
 (r"como funciona|que es nutriai|para que sirve|que hace|de que trata", "NutriAI es tu doctor de bolsillo 🦦: tomas foto de tu platillo y te digo calorías, proteína, carbs, grasa y fibra con un semáforo (qué sumar y qué evitar hoy). Si me mandas foto de tus ingredientes, te digo qué cocinar, en cuánto tiempo y cuánto les queda. Pruébalo: mándame una foto 📸"),
 (r"vida util|cuanto duran|cuanto tiempo (me )?(queda|dura)|caduc|echa a perder|se va a echar", "Si me mandas foto de tus ingredientes, te digo cuánto tiempo les queda (por ejemplo, 3-5 días en refri) para que cocines primero lo que se echa a perder 🥬⏳. Mándame la foto 📸"),
 (r"receta|ingrediente|refri|que cocino|que puedo cocinar|que preparo", "Mándame una foto de lo que tienes (refri, despensa o mesa) y te propongo recetas rápidas con esos ingredientes, con su tiempo de preparación 🍳. Es gratis en el Plan Básico."),
 (r"foto|escane|camara|analiz", "Mándame aquí mismo una foto de tu platillo (calorías y macros) o de tus ingredientes (recetas y vida útil) 📸. Se ve mejor con buena luz y el plato completo en cuadro."),
 (r"caloria|proteina|macro|carbo|grasa|fibra|nutriente", "Con una foto de tu platillo te estimo calorías, proteína, carbohidratos, grasas y fibra 💪. Son estimaciones orientativas. Mándame tu foto 📸"),
 (r"semaforo", "El semáforo 🚦 te dice qué conviene sumar hoy (verde) y qué evitar (rojo) según lo que ya comiste: por ejemplo, proteínas magras y verduras para la cena, y evitar bebidas azucaradas o exceso de sodio."),
 (r"\bquiz\b|test|cuestionario", "El quiz es gratis y corto: te da tu primer resultado y un tip de Dr. Nutri. Lo encuentras en nuestras redes y en www.nutriai.mx 🦦"),
 (r"\breto\b|7 dias|siete dias", "El Reto de 7 días es gratis 💙: una pequeña meta diaria con acompañamiento de Dr. Nutri. Pregunta en nuestras redes o en el campus. Más info en www.nutriai.mx"),
 (r"codigo de barras|barras|por voz|\bvoz\b", "En la app completa puedes registrar tu comida con foto, código de barras, voz o texto. En esta versión beta, el análisis es por foto y por texto 📸"),
 (r"descarg|instal|\bapp\b|aplicacion|pagina|sitio|web", "Puedes probar NutriAI en www.nutriai.mx o escribiéndome por aquí 🦦. El Plan Básico es gratis."),
 (r"horario|a que hora|cuando atienden|hasta que hora", "El bot te atiende 24/7 🤖. Los asesores atienden de lunes a viernes de 9:00 a 18:00 (hora CDMX). Si escribes fuera de horario, tu caso queda registrado y te respondemos al abrir."),
 (r"quien eres|como te llamas|eres un bot|eres humano|eres una persona|eres real", "Soy Dr. Nutri 🦦, el asistente automático de NutriAI. Oriento sobre alimentación, pero no diagnostico ni sustituyo a un médico. Si prefieres una persona, escribe 3."),
 (r"nutriologo|valida|confiable|precis|segur[oa]s?\b|exact", "Nuestras bases de datos alimentarias están respaldadas por un comité técnico de nutriólogos, con doble verificación para reducir falsos positivos en alérgenos y auditoría de resultados 🛡️. Aun así, las cifras son estimaciones orientativas."),
 (r"foraneo|estudiante|universidad|campus|escuela", "NutriAI está pensada para foráneos y jóvenes: recetas rápidas, económicas y nutritivas con los ingredientes que ya tienes, sin gastar de más ni sentir culpa 🎓🦦"),
 (r"deportista|gimnasio|\bgym\b|musculo|masa muscular|entren", "Para deportistas: control de macronutrientes, tiempos de ingesta e índice glucémico 🏋️. Mándame la foto de tu comida y te digo cómo va tu proteína."),
 (r"bajar de peso|control de peso|adelgaz|deficit|superavit", "Para control de peso te damos apoyo guiado para un déficit o superávit calórico sostenible ⚖️. Mándame una foto de tu comida para ver cómo vas hoy. Para un plan personalizado, escribe 3 y te paso con un asesor."),
 (r"gracias|thank|te agradezco", "¡De nada! 💙 Aquí estoy cuando quieras. Escribe *menu* para ver las opciones."),
 (r"adios|bye|hasta luego|nos vemos", "¡Hasta pronto! 🦦💙 Cuando quieras, mándame la foto de tu próxima comida."),
]
def faq_local(t):
    n = norm(t)
    for pat, ans in FAQ_RULES:
        if re.search(pat, n): return ans
    return None

# ---------- envío por canal ----------
def chunks(s, n):
    out, cur = [], ""
    for line in s.split("\n"):
        if len(cur) + len(line) + 1 > n and cur: out.append(cur.rstrip()); cur = ""
        cur += line + "\n"
    if cur.strip(): out.append(cur.rstrip())
    return out
def send(key, text, who="bot"):
    ch, uid = key.split(":", 1)
    for part in chunks(text, 3500 if ch == "wa" else 900):
        if ch == "wa":
            r = requests.post(f"{GRAPH}/{WA_PHONE_ID}/messages", headers={"Authorization": f"Bearer {WA_TOKEN}"},
                          json={"messaging_product": "whatsapp", "to": uid, "type": "text", "text": {"body": part}}, timeout=20)
            if r.status_code >= 300: print("ERROR WhatsApp al enviar:", r.status_code, r.text)
        elif ch == "ig":
            r = requests.post(f"{IG_HOST}/me/messages", params={"access_token": IG_TOKEN},
                          json={"recipient": {"id": uid}, "message": {"text": part}}, timeout=20)
            if r.status_code >= 300: print("ERROR Instagram al enviar:", r.status_code, r.text)
    log(key, who, text)

# ---------- webhooks Meta ----------
def verify():
    if request.args.get("hub.verify_token") == VERIFY: return request.args.get("hub.challenge", ""), 200
    return "token inválido", 403

def wa_process(data):
    try:
        for e in data.get("entry", []):
            for chg in e.get("changes", []):
                for m in chg["value"].get("messages", []):
                    uid, kind = m["from"], m["type"]
                    if kind == "text": out = handle("wa", uid, text=m["text"]["body"])
                    elif kind == "image":
                        meta = requests.get(f"{GRAPH}/{m['image']['id']}", headers={"Authorization": f"Bearer {WA_TOKEN}"}, timeout=20).json()
                        img = requests.get(meta["url"], headers={"Authorization": f"Bearer {WA_TOKEN}"}, timeout=30)
                        out = handle("wa", uid, image=(img.content, meta.get("mime_type", "image/jpeg")))
                    else: out = ["Por ahora entiendo texto y fotos 📸"]
                    for t in out: send(f"wa:{uid}", t)
    except Exception as ex: print("WA error", ex)

def ig_process(data):
    try:
        for e in data.get("entry", []):
            for ev in e.get("messaging", []):
                m = ev.get("message")
                if not m or m.get("is_echo"): continue
                uid, out = ev["sender"]["id"], None
                imgs = [a for a in m.get("attachments", []) if a.get("type") == "image"]
                if imgs:
                    r = requests.get(imgs[0]["payload"]["url"], timeout=30)
                    out = handle("ig", uid, image=(r.content, r.headers.get("content-type", "image/jpeg")))
                elif m.get("text"): out = handle("ig", uid, text=m["text"])
                else: out = ["Por ahora entiendo texto y fotos 📸"]
                for t in out: send(f"ig:{uid}", t)
    except Exception as ex: print("IG error", ex)

@app.route("/webhook/whatsapp", methods=["GET", "POST"])
def wa_hook():
    if request.method == "GET": return verify()
    threading.Thread(target=wa_process, args=(request.get_json(silent=True) or {},)).start(); return "ok"
@app.route("/webhook/instagram", methods=["GET", "POST"])
def ig_hook():
    if request.method == "GET": return verify()
    threading.Thread(target=ig_process, args=(request.get_json(silent=True) or {},)).start(); return "ok"

# ---------- web beta ----------
@app.route("/")
def home(): return render_template("index.html")
@app.route("/api/scan", methods=["POST"])
def api_scan():
    f = request.files.get("foto")
    if not f: return jsonify(error="Sube una foto"), 400
    try: return jsonify(scan(f.read(), f.mimetype or "image/jpeg"))
    except Exception as e: print("scan error", e); return jsonify(error="No pude analizar la foto, intenta con otra"), 500
@app.route("/api/chat", methods=["POST"])
def api_chat():
    d = request.get_json(force=True); return jsonify(replies=handle("web", d["sid"], text=d.get("text", "")))
@app.route("/api/poll")
def api_poll():
    key, after = "web:" + request.args["sid"], int(request.args.get("after", 0))
    with db() as c:
        rows = c.execute("select id,text from msgs where key=? and who='asesor' and id>?", (key, after)).fetchall()
    return jsonify(msgs=[dict(r) for r in rows])

@app.route("/api/plan", methods=["POST"])
def api_plan():
    try: return jsonify(planificador.armar(request.get_json(force=True)))
    except ValueError as e: return jsonify(error=str(e)), 400
    except Exception as e: print("plan error", e); return jsonify(error="No pude armar el plan, intenta de nuevo"), 500
@app.route("/api/plan/recetas", methods=["POST"])
def api_plan_recetas():
    try: return jsonify(texto=gemini([{"text": planificador.prompt_recetas(planificador.armar(request.get_json(force=True)))}]).strip())
    except Exception as e: print("recetas error", e); return jsonify(error="No pude conectar con la IA ahora. Usa el menú de arriba."), 500

# ---------- panel de asesores / call center ----------
PANEL = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Panel NutriAI</title>
<style>body{font-family:system-ui;background:#fdfaf0;margin:0;padding:16px;color:#17324d}.t{background:#fff;border-radius:12px;padding:14px;margin:12px 0;box-shadow:0 1px 6px #0002}
.l2{border-left:6px solid #19b5d8}.l3{border-left:6px solid #f5a21b}.m{font-size:.9rem;background:#f4f7fb;padding:8px;border-radius:8px;max-height:150px;overflow:auto}
textarea{width:100%;padding:8px}button{background:#2a64b0;color:#fff;border:0;border-radius:8px;padding:8px 14px}</style>
<img src=/static/logo_transparente.png height=60> <h2>Panel de atención</h2>
{% if not ok %}<form method=post><input type=password name=p placeholder=Contraseña> <button>Entrar</button></form>
{% else %}<p>Casos abiertos: {{tickets|length}} · <a href=/panel>Actualizar</a></p>
{% for t in tickets %}<div class="t l{{t.level}}"><b>#{{t.id}} · {{'Nivel 2 · Asesor' if t.level==2 else 'Nivel 3 · Call center'}}</b> · {{t.category}} · {{t.key}} · {{t.created}}
{% if t.contact %}<br>Contacto: {{t.contact}}{% endif %}<div class=m>{% for m in t.msgs %}<b>{{m.who}}:</b> {{m.text}}<br>{% endfor %}</div>
<form method=post action=/panel/reply><input type=hidden name=key value="{{t.key}}"><input type=hidden name=id value="{{t.id}}">
<textarea name=text rows=2 placeholder="Respuesta al cliente"></textarea><label><input type=checkbox name=close> Cerrar caso y regresar al bot</label> <button>Enviar</button></form></div>{% endfor %}{% endif %}"""
def tickets():
    with db() as c:
        ts = [dict(r) for r in c.execute("select * from tickets where status='abierto' order by level desc, id").fetchall()]
        for t in ts: t["msgs"] = [dict(r) for r in c.execute("select who,text from msgs where key=? order by id desc limit 8", (t["key"],)).fetchall()][::-1]
    return ts
@app.route("/panel", methods=["GET", "POST"])
def panel():
    if request.method == "POST" and request.form.get("p") == PANEL_PASS: session["ok"] = 1
    ok = bool(session.get("ok")); return render_template_string(PANEL, ok=ok, tickets=tickets() if ok else [])
@app.route("/panel/reply", methods=["POST"])
def panel_reply():
    if not session.get("ok"): return "no autorizado", 401
    key, text = request.form["key"], request.form.get("text", "").strip()
    if text: send(key, text, who="asesor")
    if request.form.get("close"):
        with db() as c: c.execute("update tickets set status='cerrado' where id=?", (request.form["id"],))
        upd(key, mode="bot", fails=0)
    return "<script>location='/panel'</script>"

if __name__ == "__main__": app.run(host="0.0.0.0", port=int(E("PORT", 5000)), debug=True)
