"""Planificador de quincena: presupuesto + datos del cuerpo -> porciones por comida,
lista de compras por tienda (la más barata) y menú. Los cálculos los hace el código (no la IA)."""
import json, os

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "precios.json")
KCAL_FIJAS = {"avena": 0.15, "tortilla": 0.12, "legumbre": 0.12, "lacteo": 0.09}   # % de las kcal del día
VERDURA_G, FRUTA_G = 250, 200
DIST3 = {"avena": {"desayuno": 1}, "tortilla": {"desayuno": .3, "comida": .35, "cena": .35}, "cereal": {"comida": .55, "cena": .45},
         "legumbre": {"comida": .55, "cena": .45}, "animal": {"comida": .55, "cena": .45}, "huevo": {"desayuno": .5, "comida": .25, "cena": .25},
         "lacteo": {"desayuno": .7, "cena": .3}, "grasa": {"comida": .5, "cena": .5},
         "verdura": {"desayuno": .1, "comida": .5, "cena": .4}, "fruta": {"desayuno": .5, "comida": .5}}
DIST4 = dict(DIST3, fruta={"desayuno": .25, "comida": .25, "colacion": .5},
             lacteo={"desayuno": .5, "colacion": .25, "cena": .25}, cacahuate={"colacion": 1})

def cargar():
    with open(RUTA, encoding="utf-8") as f: return json.load(f)
def mejor_precio(a):
    ps = {t: p for t, p in a["precios"].items() if p}
    t = min(ps, key=ps.get); return ps[t], t
_precio = lambda a: mejor_precio(a)[0]
_c_kcal = lambda a: _precio(a) / (a["kcal"] * 10)
_c_prot = lambda a: _precio(a) / (a["prot"] * 10)

def requerimientos(peso, estatura, edad, sexo, actividad, objetivo):
    """Mifflin-St Jeor + límites de seguridad. Devuelve (kcal, proteína g, notas)."""
    notas = []
    if edad < 18 and objetivo == 2:
        objetivo = 1; notas.append("Eres menor de 18: te armé un plan para MANTENER tu peso. Para bajar de peso consulta a un nutriólogo.")
    tmb = 10 * peso + 6.25 * estatura - 5 * edad + (5 if sexo == "h" else -161)
    kcal = tmb * {1: 1.2, 2: 1.55, 3: 1.725}[actividad] * {1: 1.0, 2: 0.85, 3: 1.10}[objetivo]
    piso = 1800 if sexo == "h" else 1500
    if kcal < piso: kcal = piso; notas.append(f"Ajusté tus calorías al mínimo seguro ({piso} kcal). Para comer menos que eso, consulta a un nutriólogo.")
    prot = min(peso * {1: 1.4, 2: 1.8, 3: 1.8}[objetivo], peso * 2.0)
    return round(kcal), round(prot), notas, objetivo

def construir(A, kcal, prot, var):
    rol = {}
    for i, a in A.items(): rol.setdefault(a["rol"], []).append(i)
    n = 2 if var else 1
    sel = {"avena": ["avena"], "tortilla": ["tortilla"],
           "cereal": sorted(rol["cereal"], key=lambda i: _c_kcal(A[i]))[:n],
           "legumbre": sorted(rol["legumbre"], key=lambda i: _c_prot(A[i]))[:n],
           "animal": sorted(rol["animal"], key=lambda i: _c_prot(A[i]))[:3 if var else 2],
           "lacteo": ["leche", "yogurt"] if var else ["leche"],
           "grasa": ["aceite", "cacahuate"] if var else ["aceite"],
           "verdura": sorted(rol["verdura"], key=lambda i: _precio(A[i]))[:n + 1],
           "fruta": sorted(rol["fruta"], key=lambda i: _precio(A[i]))[:n]}
    g = {}
    kc = lambda i, x: x * A[i]["kcal"] / 100
    pr = lambda i, x: x * A[i]["prot"] / 100
    def por_kcal(r, k):
        for i in sel[r]: g[i] = (k / len(sel[r])) / A[i]["kcal"] * 100
    for r, f in KCAL_FIJAS.items(): por_kcal(r, kcal * f)
    for i, s in zip(sel["grasa"], [.6, .4] if len(sel["grasa"]) == 2 else [1]): g[i] = kcal * .07 * s / A[i]["kcal"] * 100
    for i in sel["verdura"]: g[i] = VERDURA_G / len(sel["verdura"])
    for i in sel["fruta"]: g[i] = FRUTA_G / len(sel["fruta"])
    base = [i for r in ("avena", "tortilla", "legumbre", "lacteo", "grasa", "verdura", "fruta") for i in sel[r]]
    k_base, p_base, k_an = sum(kc(i, g[i]) for i in base), sum(pr(i, g[i]) for i in base), 0
    for _ in range(5):     # el cereal rellena las calorías que faltan; la proteína animal completa la proteína
        por_kcal("cereal", max(.10 * kcal, kcal - k_base - k_an))
        falta = max(0, prot - p_base - sum(pr(i, g[i]) for i in sel["cereal"]))
        for i in sel["animal"]: g[i] = (falta / len(sel["animal"])) / A[i]["prot"] * 100
        k_an = sum(kc(i, g[i]) for i in sel["animal"])
        if k_an > .30 * kcal:
            for i in sel["animal"]: g[i] *= .30 * kcal / k_an
            k_an = .30 * kcal
    out = {}
    for i, x in g.items():
        paso = A[i].get("pza_g") or 5
        r = round(x / paso) * paso
        if r == 0 and x >= paso * .4: r = paso
        if r > 0: out[i] = r
    return {r: [i for i in ids if i in out] for r, ids in sel.items()}, out

def costear(A, g, dias):
    it = []
    for i, gd in g.items():
        a = A[i]; p, t = mejor_precio(a); kg = gd * dias / 1000
        it.append({"id": i, "nombre": a["nombre"], "rol": a["rol"], "unidad": a.get("unidad", "g"), "g_dia": gd,
                   "pzas_dia": round(gd / a["pza_g"], 1) if a.get("pza_g") else None,
                   "kg_total": round(kg, 2), "tienda": t, "precio_kg": p, "costo": round(kg * p, 2)})
    return it

def _partir(n, d):
    base = {m: int(n * s) for m, s in d.items()}
    for m in sorted(d, key=lambda m: n * d[m] - base[m], reverse=True)[:n - sum(base.values())]: base[m] += 1
    return base

def repartir(A, g, comidas):
    dist = DIST4 if comidas == 4 else DIST3
    orden = ["desayuno", "comida", "cena"] + (["colacion"] if comidas == 4 else [])
    res = {m: [] for m in orden}
    for i, gd in g.items():
        a = A[i]; d = dist.get(i) or dist[a["rol"]]
        if a.get("pza_g"):
            for m, k in _partir(int(round(gd / a["pza_g"])), d).items():
                if k: res[m].append({"nombre": a["nombre"], "g": k * a["pza_g"], "pzas": k, "unidad": a["unidad"], "kcal": round(k * a["pza_g"] * a["kcal"] / 100)})
        else:
            for m, s in d.items():
                x = round(gd * s / 5) * 5
                if x: res[m].append({"nombre": a["nombre"], "g": x, "pzas": None, "unidad": a["unidad"], "kcal": round(x * a["kcal"] / 100)})
    return {m: {"items": v, "kcal": sum(x["kcal"] for x in v)} for m, v in res.items()}

def menu(A, sel, dias, comidas):
    n = lambda i: A[i]["nombre"].lower(); cap = lambda s: s[:1].upper() + s[1:]
    pick = lambda l, d, df: l[d % len(l)] if l else df
    C, L, AN, V, F = (sel[k] for k in ("cereal", "legumbre", "animal", "verdura", "fruta"))
    AN_main = [i for i in AN if i != "huevo"] or AN       # el huevo va sobre todo en el desayuno
    out, ai, li = [], 0, 0
    for d in range(dias):
        f, v1, v2, c = n(pick(F, d, "plátano")) if F else "fruta", n(pick(V, d, "jitomate")), n(pick(V, d + 1, "cebolla")), n(pick(C, d, "arroz"))
        des = f"Huevo revuelto con {v1}, tortillas y {f}" if "huevo" in AN and d % 2 == 1 else f"Avena con leche y {f}"
        if (d % 3 == 1 and L) or not AN: com = f"{cap(n(pick(L, li, 'frijol')))} con {c} y {v1}"; li += 1
        else: com = f"{cap(n(pick(AN_main, ai, 'huevo')))} con {v1}, {c} y tortillas"; ai += 1
        if d % 2 == 0 and L: cen = f"Tacos de {n(pick(L, li, 'frijol'))} con {v2}"; li += 1
        else: cen = f"{cap(n(pick(AN_main, ai, 'huevo')))} con {v2} y tortillas"; ai += 1
        dia = {"dia": d + 1, "desayuno": des, "comida": com, "cena": cen}
        if comidas == 4: dia["colacion"] = f"Yogurt con {f}" if "yogurt" in sel["lacteo"] else f"{cap(f)} con cacahuates"
        out.append(dia)
    return out

def armar(d, dias=15):
    try:
        pres, peso, est, edad = (float(d[k]) for k in ("presupuesto", "peso", "estatura", "edad"))
        sexo = str(d["sexo"]).lower()[:1]; sexo = "h" if sexo == "h" else "m"
        act, obj, comidas = int(d["actividad"]), int(d["objetivo"]), int(d.get("comidas", 3))
    except (KeyError, ValueError, TypeError): raise ValueError("Faltan datos o hay un número inválido.")
    if not (100 <= pres <= 20000): raise ValueError("El presupuesto debe estar entre $100 y $20,000.")
    if not (30 <= peso <= 250 and 120 <= est <= 230 and 10 <= edad <= 90): raise ValueError("Revisa peso, estatura y edad.")
    if edad < 15: raise ValueError("Este planificador es para mayores de 15 años. Habla con un asesor.")
    if act not in (1, 2, 3) or obj not in (1, 2, 3) or comidas not in (3, 4): raise ValueError("Actividad, objetivo o comidas inválidos.")
    data = cargar(); A = data["alimentos"]
    kcal, prot, notas, obj = requerimientos(peso, est, edad, sexo, act, obj)
    manual = d.get("kcal")
    try: manual = int(float(manual)) if manual not in (None, "", 0) else None
    except (ValueError, TypeError): manual = None
    if manual and 500 <= manual <= 6000:
        if manual < kcal * .8: notas.append(f"Hoy comes ≈{manual} kcal y tu cuerpo necesita ≈{kcal}: comer de menos puede dejarte sin energía. El plan ya cubre lo que necesitas.")
        elif manual > kcal * 1.2 and obj == 2: notas.append(f"Hoy comes ≈{manual} kcal; para bajar grasa el plan baja a ≈{kcal}.")
    for var in (True, False):
        sel, g = construir(A, kcal, prot, var)
        items = costear(A, g, dias); costo = round(sum(i["costo"] for i in items), 2)
        if costo <= pres: break
    modo = "variado" if var else "económico"
    kreal = round(sum(gd * A[i]["kcal"] / 100 for i, gd in g.items())); preal = round(sum(gd * A[i]["prot"] / 100 for i, gd in g.items()))
    tiendas = {}
    for t in data["tiendas"]:
        if all(A[i]["precios"].get(t) for i in g): tiendas[t] = round(sum(A[i]["precios"][t] * gd * dias / 1000 for i, gd in g.items()), 2)
    por_tienda = {}
    for it in sorted(items, key=lambda x: -x["costo"]): por_tienda.setdefault(it["tienda"], []).append(it)
    alcanza = costo <= pres
    p = {"dias": dias, "modo": modo, "presupuesto": pres, "kcal_obj": kcal, "prot_obj": prot, "kcal_real": kreal, "prot_real": preal,
         "costo_total": costo, "costo_dia": round(costo / dias, 2), "alcanza": alcanza, "notas": notas, "comidas_dia": comidas,
         "sobrante": round(pres - costo, 2) if alcanza else 0, "faltante": 0 if alcanza else round(costo - pres, 2),
         "dias_alcanza": dias if alcanza else int(pres // (costo / dias)), "items": items, "por_tienda": por_tienda,
         "una_tienda": dict(sorted(tiendas.items(), key=lambda x: x[1])), "comidas": repartir(A, g, comidas),
         "menu": menu(A, sel, dias, comidas), "aviso": data["_aviso"]}
    if alcanza and modo == "variado" and p["sobrante"] > .2 * pres:
        p["sugerencia"] = f"Te sobran ${p['sobrante']:.0f}: puedes subir la calidad (por ejemplo pechuga de pollo en lugar de muslo) o ahorrarlos."
    return p

# ---------- textos para chat ----------
ICONO = {"desayuno": "🌅 Desayuno", "comida": "☀️ Comida", "cena": "🌙 Cena", "colacion": "🍎 Colación"}
def _porcion(x):
    return f"{x['nombre'].lower()} {x['pzas']:g} pza" if x["pzas"] else f"{x['nombre'].lower()} {x['g']} {x['unidad']}"
def _sec_lista(p):
    return "🏬 *Dónde comprar cada cosa (lo más barato)*\n" + "\n\n".join(f"*{tn}* (${sum(i['costo'] for i in its):.0f})\n" + "\n".join(f"• {i['nombre']}: {i['kg_total']:g} {'l' if i['unidad']=='ml' else 'kg'} (${i['costo']:.0f})" for i in its) for tn, its in p["por_tienda"].items())
def texto_chat(p):
    d = p["dias"]
    t = [f"🛒 *Tu plan de {d} días ({p['modo']})*\n🔥 {p['kcal_real']} kcal/día · 💪 {p['prot_real']} g de proteína/día (meta {p['prot_obj']} g)\n💰 Costo ${p['costo_total']:.0f} de tus ${p['presupuesto']:.0f} (≈${p['costo_dia']:.0f} al día)"]
    if p["alcanza"]: t[0] += f"\n✅ Te sobran ${p['sobrante']:.0f}"
    else: t[0] += f"\n⚠️ Te faltan ${p['faltante']:.0f}: con tu presupuesto alcanzas para {p['dias_alcanza']} de {d} días. Compra para esos días y completa con la siguiente quincena, o prioriza la lista en el *Mercado local*."
    t += [n for n in p["notas"]]
    t.append("🍽️ *Cómo repartir tu día*\n" + "\n".join(f"{ICONO[m]} (~{v['kcal']} kcal): " + ", ".join(_porcion(x) for x in v["items"]) for m, v in p["comidas"].items()))
    t.append(_sec_lista(p))
    if p["una_tienda"]:
        u = list(p["una_tienda"].items())
        t.append("📊 *Si compras TODO en una sola tienda*\n" + "\n".join(f"• {k}: ${v:.0f}" for k, v in u) + f"\n\nCombinando tiendas ahorras ${u[0][1]-p['costo_total']:.0f} frente a la mejor tienda única.")
    t.append("📅 *Menú de ejemplo (3 días)*\n" + "\n\n".join(f"Día {m['dia']}\n" + "\n".join(f"{ICONO[k].split()[0]} {m[k]}" for k in ("desayuno", "comida", "cena", "colacion") if k in m) for m in p["menu"][:3]))
    if p.get("sugerencia"): t.append("💡 " + p["sugerencia"])
    t.append("_Precios de REFERENCIA de ejemplo: verifícalos en tienda. Las cantidades son orientativas y no sustituyen a un nutriólogo._\n\nEscribe *menu15* para ver todos los días, *recetas* para recetas con IA o *lista* para repetir tu lista de compras.")
    return "\n\n".join(t)
def texto_menu(p):
    return "📅 *Tu menú completo*\n\n" + "\n\n".join(f"Día {m['dia']}\n" + "\n".join(f"{ICONO[k].split()[0]} {m[k]}" for k in ("desayuno", "comida", "cena", "colacion") if k in m) for m in p["menu"])
def texto_lista(p):
    return _sec_lista(p)
def prompt_recetas(p):
    ing = ", ".join(i["nombre"].lower() for i in p["items"])
    rep = "; ".join(f"{ICONO[m]}: " + ", ".join(_porcion(x) for x in v["items"]) for m, v in p["comidas"].items())
    return (f"Con SOLO estos ingredientes: {ing} (más sal, especias y agua), escribe 5 recetas baratas y rápidas para un estudiante, "
            f"respetando estas porciones diarias: {rep}. Para cada receta: nombre, ingredientes con gramos por porción y 3 pasos cortos. "
            "Español, máximo 90 palabras por receta, sin consejos médicos.")
