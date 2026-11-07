"""Planificador v2: presupuesto + salud -> menú sostenible (meal prep del domingo), porciones por comida y compras con marcas."""
import json, os, re, math, unicodedata
class PlanBloqueado(ValueError): pass
RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "precios.json")
KCAL_FIJAS = {"avena": .15, "tortilla": .12, "legumbre": .12, "lacteo": .09}
VERDURA_G, FRUTA_G = 200, 150
SPLIT = {3: {"desayuno": .30, "comida": .45, "cena": .25}, 4: {"desayuno": .27, "colacion": .12, "comida": .38, "cena": .23}}
DIST3 = {"avena": {"desayuno": 1}, "tortilla": {'desayuno': 0.6, 'comida': 0.22, 'cena': 0.18}, "cereal": {'comida': 0.8, 'cena': 0.2},
         "legumbre": {"comida": .65, "cena": .35}, "animal": {'comida': 0.55, 'cena': 0.45}, "huevo": {"desayuno": .5, "comida": .25, "cena": .25},
         "lacteo": {"desayuno": .75, "cena": .25}, "grasa": {"comida": .6, "cena": .4}, "verdura": {"comida": .6, "cena": .4},
         "fruta": {"desayuno": .5, "comida": .5}}
DIST4 = dict(DIST3, avena={'desayuno': 0.6, 'colacion': 0.4}, fruta={"desayuno": .25, "comida": .25, "colacion": .5}, lacteo={"desayuno": .4, "colacion": .4, "cena": .2}, cacahuate={"colacion": 1})
ROL_TXT = {"animal": "Proteína", "legumbre": "Legumbres", "cereal": "Cereal", "avena": "Avena", "tortilla": "Tortillas", "lacteo": "Lácteo", "grasa": "Grasa", "verdura": "Verdura", "fruta": "Fruta"}
ICONO = {"desayuno": "🌅 Desayuno", "comida": "☀️ Comida", "cena": "🌙 Cena", "colacion": "🍎 Colación"}
def cargar():
    with open(RUTA, encoding="utf-8") as f: return json.load(f)
def mejor_precio(a):
    ps = {t: p for t, p in a["precios"].items() if p}; t = min(ps, key=ps.get); return ps[t], t
_precio = lambda a: mejor_precio(a)[0]
_c_kcal = lambda a: _precio(a) / (a["kcal"] * 10)
_c_prot = lambda a: _precio(a) / (a["prot"] * 10)
def _n(t): return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")

# ---------- salud: alergias, suplementos y condiciones ----------
NEG = re.compile(r"^\s*(no|ninguna?|nada|ninguno|n/?a|sin ninguna?|no tengo|no tomo)\W*$")
GRUPOS = [(r"marisc|pescado|camaron|atun|sardina", ["atun", "sardina"]), (r"lacteo|lactosa|leche|queso|yogur", ["leche", "yogurt"]), (r"huevo", ["huevo"]),
          (r"cacahuate|nuez|nueces|mani\b|frutos secos", ["cacahuate"]), (r"gluten|trigo|celiac", ["pasta", "avena"]), (r"\bpollo\b|\baves?\b", ["muslo", "pechuga"]),
          (r"\bres\b|carne", ["molida"]), (r"legumbre|frijol|lenteja|garbanzo", ["frijol", "lenteja", "garbanzo"])]
MSG_TCA = "Gracias por contármelo 💙 Para esto lo mejor es el acompañamiento de un profesional de la salud, así que no te voy a armar un plan con números. Si quieres, te paso con un asesor que te orienta."
MSG_MED = "Por tu condición (embarazo, lactancia o una enfermedad renal, hepática, cardíaca o cáncer) necesitas un plan hecho por tu médico o nutriólogo, así que no te armo uno aquí. Si quieres, te paso con un asesor."
def salud(A, alerg, sup, cond):
    ex, notas, off = set(), [], 0
    al = _n(alerg)
    if al and not NEG.match(al):
        for pat, ids in GRUPOS:
            if re.search(pat, al): ex.update(ids)
        for i, a in A.items():
            w = _n(a["nombre"]).split()[0]
            if len(w) > 3 and (w in al or i in al): ex.add(i)
        nom = ", ".join(sorted(A[i]["nombre"].lower() for i in ex if i in A))
        notas.append("Alergias o intolerancias: excluí " + (nom or "lo que mencionaste") + ". Si tu alergia no está en esa lista, díselo a un asesor y revisa siempre las etiquetas.")
    co = _n(cond)
    if co and not NEG.match(co):
        if re.search(r"anorex|bulim|atracon|trastorno (de la )?aliment|\btca\b|purg", co): raise PlanBloqueado(MSG_TCA)
        if re.search(r"embaraz|lactan|renal|rinon|higado|hepat|cirrosis|cancer|infarto|cardiac|corazon", co): raise PlanBloqueado(MSG_MED)
        hit = False
        if "diabet" in co: hit = True; notas.append("Diabetes: reparte tus carbohidratos en todas las comidas, prefiere fruta entera y evita jugos y bebidas azucaradas. Confirma las porciones con tu médico.")
        if re.search(r"hipertens|presion alta", co): hit = True; ex.update(["atun", "sardina"]); notas.append("Hipertensión: cocina sin sal añadida (usa limón, ajo y especias) y evita enlatados y embutidos. Confirma el plan con tu médico.")
        if re.search(r"sobrepeso|obesidad|colesterol|trigliceridos", co): hit = True; notas.append("Sobrepeso o colesterol: prefiere hervido, horneado o a la plancha en lugar de frito, y revisa tu avance con un nutriólogo.")
        if not hit: notas.append("Mencionaste una condición médica: consulta con tu médico antes de seguir el plan.")
        notas.append("Con una condición médica, este plan es solo orientativo: compártelo con tu médico o nutriólogo.")
    su = _n(sup)
    if su and not NEG.match(su):
        hit = False
        if re.search(r"proteina|whey|suero", su): hit = True; off = 24; notas.append("Proteína en polvo: asumí 1 scoop al día (≈24 g de proteína) y la descontré de tu comida. Si tomas más, necesitas menos proteína de comida aún.")
        if "creatina" in su: hit = True; notas.append("Creatina: no cambia tus calorías; toma suficiente agua y consulta a tu médico si tienes problemas renales.")
        if re.search(r"vitamin|multivit|omega|hierro|calcio|magnesio|zinc", su): hit = True; notas.append("Vitaminas y minerales en pastilla: no sustituyen comida; consulta la dosis con tu médico o nutriólogo.")
        if not hit: notas.append("Mencionaste suplementos: ninguno cambia este plan, pero consulta con tu médico si tomas medicamentos.")
    return ex, notas, off

def requerimientos(peso, estatura, edad, sexo, actividad, objetivo):
    notas = []
    if edad < 18 and objetivo == 2: objetivo = 1; notas.append("Eres menor de 18: te armé un plan para MANTENER tu peso. Para bajar de peso consulta a un nutriólogo.")
    tmb = 10 * peso + 6.25 * estatura - 5 * edad + (5 if sexo == "h" else -161)
    kcal = tmb * {1: 1.2, 2: 1.55, 3: 1.725}[actividad] * {1: 1.0, 2: 0.85, 3: 1.10}[objetivo]
    piso = 1800 if sexo == "h" else 1500
    if kcal < piso: kcal = piso; notas.append(f"Ajusté tus calorías al mínimo seguro ({piso} kcal). Para comer menos que eso, consulta a un nutriólogo.")
    return round(kcal), min(peso * {1: 1.4, 2: 1.8, 3: 1.8}[objetivo], peso * 2.0), notas, objetivo

def construir(A, kcal, prot, var, excl):
    rol = {}
    for i, a in A.items():
        if i not in excl: rol.setdefault(a["rol"], []).append(i)
    n = 2 if var else 1
    an = [i for i in rol.get("animal", []) if i not in ("atun", "sardina")] or rol.get("animal", [])
    ok = lambda ids: [i for i in ids if i not in excl]
    sel = {"avena": ok(["avena"]), "tortilla": ok(["tortilla"]),
           "cereal": sorted(rol.get("cereal", []), key=lambda i: _c_kcal(A[i]))[:n], "legumbre": sorted(rol.get("legumbre", []), key=lambda i: _c_prot(A[i]))[:n],
           "animal": sorted(an, key=lambda i: _c_prot(A[i]))[:3 if var else 2], "lacteo": ok(["leche", "yogurt"] if var else ["leche"]),
           "grasa": ok(["aceite", "cacahuate"] if var else ["aceite"]), "verdura": sorted(rol.get("verdura", []), key=lambda i: _precio(A[i]))[:n + 1],
           "fruta": sorted(rol.get("fruta", []), key=lambda i: _precio(A[i]))[:n]}
    g = {}
    kc = lambda i, x: x * A[i]["kcal"] / 100
    pr = lambda i, x: x * A[i]["prot"] / 100
    def por_kcal(r, k):
        for i in sel[r]: g[i] = (k / len(sel[r])) / A[i]["kcal"] * 100
    for r, f in KCAL_FIJAS.items():
        if sel[r]: por_kcal(r, kcal * f)
    for i, s in zip(sel["grasa"], [.6, .4] if len(sel["grasa"]) == 2 else [1]): g[i] = kcal * .07 * s / A[i]["kcal"] * 100
    for i in sel["verdura"]: g[i] = VERDURA_G / len(sel["verdura"])
    for i in sel["fruta"]: g[i] = FRUTA_G / len(sel["fruta"])
    base = [i for r in ("avena", "tortilla", "legumbre", "lacteo", "grasa", "verdura", "fruta") for i in sel[r]]
    k_base, p_base, k_an = sum(kc(i, g[i]) for i in base), sum(pr(i, g[i]) for i in base), 0
    for _ in range(5):
        if sel["cereal"]: por_kcal("cereal", max(.10 * kcal, kcal - k_base - k_an))
        falta = max(0, prot - p_base - sum(pr(i, g[i]) for i in sel["cereal"]))
        for i in sel["animal"]: g[i] = (falta / len(sel["animal"])) / A[i]["prot"] * 100
        k_an = sum(kc(i, g[i]) for i in sel["animal"])
        if k_an > .30 * kcal and sel["animal"]:
            for i in sel["animal"]: g[i] *= .30 * kcal / k_an
            k_an = .30 * kcal
    out = {}
    for i, x in g.items():
        paso = A[i].get("pza_g") or 5; r = round(x / paso) * paso
        if r == 0 and x >= paso * .4: r = paso
        if r > 0: out[i] = r
    return {r: [i for i in ids if i in out] for r, ids in sel.items()}, out

def _paq(a, tot):
    pk = a.get("pack_g", 1000); return -(-int(tot) // pk), math.ceil(_precio(a) * pk / 1000)
def costear(A, g, dias):
    it = []
    for i, gd in g.items():
        a = A[i]; p, t = mejor_precio(a); paq, pp = _paq(a, gd * dias)
        it.append({"id": i, "nombre": a["nombre"], "rol": a["rol"], "unidad": a.get("unidad", "g"), "g_dia": gd, "kg_total": round(gd * dias / 1000, 2),
                   "tienda": t, "paquetes": paq, "pres": a.get("pres", ""), "alt": a.get("alt", ""), "precio_paq": pp, "costo": paq * pp, "verificado": a.get("verificado", "")})
    return it

def _partir(n, d):
    base = {m: int(n * s) for m, s in d.items()}
    for m in sorted(d, key=lambda m: n * d[m] - base[m], reverse=True)[:n - sum(base.values())]: base[m] += 1
    return base
def repartir(A, g, comidas):
    dist = DIST4 if comidas == 4 else DIST3
    res = {m: [] for m in SPLIT[comidas]}
    for i, gd in g.items():
        a = A[i]; d = dist.get(i) or dist[a["rol"]]
        if a.get("pza_g"):
            for m, k in _partir(int(round(gd / a["pza_g"])), d).items():
                if k: res[m].append((a["rol"], a["nombre"], k * a["pza_g"], k, a["unidad"], k * a["pza_g"] * a["kcal"] / 100))
        else:
            for m, s in d.items():
                x = round(gd * s / 5) * 5
                if x: res[m].append((a["rol"], a["nombre"], x, None, a["unidad"], x * a["kcal"] / 100))
    out = {}
    for m, its in res.items():
        lin = []
        for r in ROL_TXT:
            xs = [t for t in its if t[0] == r]
            if not xs: continue
            if r in ("verdura", "fruta"): lin.append(f"{ROL_TXT[r]}: {sum(t[2] for t in xs)} g ({', '.join(t[1].lower() for t in xs)})")
            else: lin.append(f"{ROL_TXT[r]}: " + ", ".join(f"{t[1].lower()} {t[3]} pza" if t[3] else f"{t[1].lower()} {t[2]} {t[4]}" for t in xs))
        out[m] = {"lineas": lin, "kcal": round(sum(t[5] for t in its))}
    return out

def menu(A, sel, dias, comidas):
    nm = lambda i: A[i]["nombre"].lower(); cap = lambda s: s[:1].upper() + s[1:]
    AN = [nm(i) for i in sel["animal"] if i != "huevo"] or [nm(i) for i in sel["animal"]]
    L = [nm(i) for i in sel["legumbre"]]; C = [nm(i) for i in sel["cereal"]] or ["tortillas"]
    V = [nm(i) for i in sel["verdura"]] or ["verduras"]; F = [nm(i) for i in sel["fruta"]] or ["fruta"]
    hue, yog, lec = "huevo" in sel["animal"], "yogurt" in sel["lacteo"], "leche" in sel["lacteo"]
    p = lambda l, d: l[d % len(l)] if l else ""
    sem = []
    for d in range(7):
        c, v1, v2, f = p(C, d), p(V, d), p(V, d + 1), p(F, d)
        a1 = p(AN, d) or p(L, d) or "huevo"; a2 = p(AN, d + 1) or p(L, d + 1) or "huevo"; l1 = p(L, d) or a1
        des = [f"Avena cocida con {'leche' if lec else 'agua'}, {f} y canela", f"Huevo revuelto con {v1} y 2 tortillas" if hue else f"Avena con {f} y cacahuate",
               f"Avena fría (lista desde el domingo) con {'yogurt' if yog else 'leche' if lec else 'agua'} y {f}"][d % 3]
        com = [f"Guisado de {a1} en salsa de jitomate con {c} y {v1}", f"{cap(l1)} de la olla con {c}, {v2} y tortillas", f"Plato de {a2} con {c} y ensalada de {v1}",
               f"Sopa de {c} con {v1}, {v2} y {a1}", f"Tacos de {a1} con {v1} y {l1}", f"{cap(l1)} con {c} y {v2}" + (", más un huevo estrellado" if hue else ""),
               f"Bowl de {c} con {a2}, {l1} y {v1}"][d]
        cen = [f"Tacos de {l1} con {v1}", f"Tacos de {a2} con {v2}", f"Tostadas de {l1} con {v1}", "Huevo a la mexicana con tortillas" if hue else f"Tacos de {a1} con {v1}",
               f"Caldo ligero de {v1} con {a1}", f"Ensalada tibia de {c} con {a2} y {v1}", f"Sopa de {v1} con tortillas y {l1}"][d]
        dia = {"desayuno": des, "comida": com, "cena": cen}
        if comidas == 4: dia["colacion"] = f"Yogurt con {f}" if yog else f"{cap(f)} con cacahuates"
        sem.append(dia)
    return [dict(sem[d % 7], dia=d + 1) for d in range(dias)]

def prep(A, sel, g):
    nm = lambda ids: " y ".join(A[i]["nombre"].lower() for i in ids)
    tot = lambda ids: int(round(sum(g.get(i, 0) for i in ids) * 5 / 10) * 10)
    L = []
    if sel["cereal"]: L.append(f"Cereal: cuece {tot(sel['cereal'])} g de {nm(sel['cereal'])} (en crudo) y guárdalo en recipientes.")
    if sel["legumbre"]: L.append(f"Legumbres: cuece {tot(sel['legumbre'])} g de {nm(sel['legumbre'])} en olla exprés con cebolla y ajo; porciónalas.")
    ani = [i for i in sel["animal"] if i != "huevo"]
    if ani: L.append(f"Carne o pollo: guisa {tot(ani)} g de {nm(ani)} en salsa de jitomate y reparte en 5 recipientes.")
    if "huevo" in sel["animal"]: L.append(f"Huevos: hierve {int(g['huevo'] / 50 * 5)} huevos; los demás se hacen frescos en 3 minutos.")
    if sel["avena"]: L.append("Desayuno: prepara avena fría para 5 días (avena y leche en frascos).")
    if sel["verdura"]: L.append(f"Verduras: lava y corta {tot(sel['verdura'])} g ({nm(sel['verdura'])}) y guárdalas secas en recipientes.")
    L.append("Entre semana solo calientas y armas tu plato en 10 minutos. Lo preparado dura de 3 a 4 días en el refri: congela las porciones de jueves y viernes y guárdalo todo en las 2 horas siguientes a cocinarlo.")
    return L

def armar(d, dias=15):
    try:
        pres, peso, est, edad = (float(d[k]) for k in ("presupuesto", "peso", "estatura", "edad"))
        sexo = "h" if str(d["sexo"]).lower()[:1] == "h" else "m"
        act, obj, comidas = int(d["actividad"]), int(d["objetivo"]), int(d.get("comidas", 3))
    except (KeyError, ValueError, TypeError): raise ValueError("Faltan datos o hay un número inválido.")
    if not (100 <= pres <= 20000): raise ValueError("El presupuesto debe estar entre $100 y $20,000.")
    if not (30 <= peso <= 250 and 120 <= est <= 230 and 10 <= edad <= 90): raise ValueError("Revisa peso, estatura y edad.")
    if edad < 15: raise ValueError("Este planificador es para mayores de 15 años. Habla con un asesor.")
    if act not in (1, 2, 3) or obj not in (1, 2, 3) or comidas not in (3, 4): raise ValueError("Actividad, objetivo o comidas inválidos.")
    data = cargar(); A = data["alimentos"]
    ex, nsalud, off = salud(A, d.get("alergias"), d.get("suplementos"), d.get("condiciones"))
    kcal, prot, notas, obj = requerimientos(peso, est, edad, sexo, act, obj)
    prot = max(peso * .8, prot - off); notas += nsalud
    try: manual = int(float(d.get("kcal") or 0))
    except (ValueError, TypeError): manual = 0
    if 500 <= manual <= 6000:
        if manual < kcal * .8: notas.append(f"Hoy comes ≈{manual} kcal y tu cuerpo necesita ≈{kcal}: comer de menos puede dejarte sin energía. El plan ya cubre lo que necesitas.")
        elif manual > kcal * 1.2 and obj == 2: notas.append(f"Hoy comes ≈{manual} kcal; para bajar grasa el plan baja a ≈{kcal}.")
    for var in (True, False):
        sel, g = construir(A, kcal, prot, var, ex); items = costear(A, g, dias); costo = round(sum(i["costo"] for i in items), 2)
        if not var or costo <= .85 * pres: break
    kreal = round(sum(x * A[i]["kcal"] / 100 for i, x in g.items())); preal = round(sum(x * A[i]["prot"] / 100 for i, x in g.items()))
    if preal < prot * .85: notas.append(f"Con tus restricciones la proteína quedó en {preal} g (meta {round(prot)} g). Un nutriólogo puede ayudarte a completarla.")
    tiendas = {t: sum(_paq(A[i], x * dias)[0] * math.ceil(A[i]["precios"][t] * A[i].get("pack_g", 1000) / 1000) for i, x in g.items())
               for t in data["tiendas"] if all(A[i]["precios"].get(t) for i in g)}
    por_tienda = {}
    for it in sorted(items, key=lambda x: -x["costo"]): por_tienda.setdefault(it["tienda"], []).append(it)
    alcanza = costo <= pres
    p = {"dias": dias, "modo": "variado" if var else "económico", "presupuesto": pres, "kcal_obj": kcal, "prot_obj": round(prot), "kcal_real": kreal, "prot_real": preal,
         "costo_total": costo, "costo_dia": round(costo / dias, 2), "alcanza": alcanza, "notas": notas, "comidas_dia": comidas,
         "sobrante": round(pres - costo, 2) if alcanza else 0, "faltante": 0 if alcanza else round(costo - pres, 2),
         "dias_alcanza": dias if alcanza else int(pres // (costo / dias)), "items": items, "por_tienda": por_tienda,
         "una_tienda": dict(sorted(tiendas.items(), key=lambda x: x[1])), "comidas": repartir(A, g, comidas), "menu": menu(A, sel, dias, comidas),
         "prep": prep(A, sel, g), "aviso": data["_aviso"]}
    if alcanza and p["sobrante"] > .25 * pres: p["sugerencia"] = f"Te sobran ${p['sobrante']:.0f}: puedes subir la calidad (por ejemplo, pechuga en lugar de muslo) o ahorrarlos."
    return p

# ---------- textos para chat ----------
def _sec_lista(p):
    t = "🏬 *Dónde comprar y qué marca* (producto recomendado × paquetes)\n"
    for tn, its in p["por_tienda"].items():
        t += f"\n*{tn}* (${sum(i['costo'] for i in its):.0f})\n" + "\n".join(f"• {i['nombre']}: {i['pres']} × {i['paquetes']} = ${i['costo']:.0f}" + (" ✓ precio verificado" if i["verificado"] else "") for i in its) + "\n"
    return t.rstrip() + "\n\n_Cada producto tiene alternativa económica: la marca propia de la tienda o granel._"
def _sec_sem(p, n=7):
    return "\n\n".join(f"Día {m['dia']}\n" + "\n".join(f"{ICONO[k].split()[0]} {m[k]}" for k in ("desayuno", "comida", "cena", "colacion") if k in m) for m in p["menu"][:n])
def texto_chat(p):
    d = p["dias"]
    t = [f"🛒 *Tu plan de {d} días ({p['modo']})*\n🔥 {p['kcal_real']} kcal/día · 💪 {p['prot_real']} g de proteína/día (meta {p['prot_obj']} g)\n💰 Costo ${p['costo_total']:.0f} de tus ${p['presupuesto']:.0f} (≈${p['costo_dia']:.0f} al día)"]
    if p["alcanza"]: t[0] += f"\n✅ Te sobran ${p['sobrante']:.0f}"
    else: t[0] += f"\n⚠️ Te faltan ${p['faltante']:.0f}: alcanzas para {p['dias_alcanza']} de {d} días. Compra para esos días y completa con la siguiente quincena, o prioriza el *Mercado local*."
    t += p["notas"]
    t.append("🍽️ *Cómo repartir tu día*\n" + "\n\n".join(f"{ICONO[m]} (~{v['kcal']} kcal)\n" + "\n".join("• " + x for x in v["lineas"]) for m, v in p["comidas"].items()))
    t.append("🍳 *Domingo de preparación (2 a 3 horas)*\n" + "\n".join(f"{n}. {x}" for n, x in enumerate(p["prep"], 1)))
    t.append("📅 *Semana tipo (se repite todas las semanas)*\n\n" + _sec_sem(p))
    t.append(_sec_lista(p))
    if p["una_tienda"]:
        u = list(p["una_tienda"].items())
        t.append("📊 *Si compras TODO en una sola tienda*\n" + "\n".join(f"• {k}: ${v:.0f}" for k, v in u) + f"\n\nCombinando tiendas ahorras ${u[0][1]-p['costo_total']:.0f} frente a la mejor tienda única.")
    if p.get("sugerencia"): t.append("💡 " + p["sugerencia"])
    t.append("_Precios y marcas de REFERENCIA: verifícalos en tienda. Las cantidades son orientativas y no sustituyen a un nutriólogo._\n\nEscribe *menu15* para el menú, *recetas* para recetas con IA o *lista* para repetir tu lista de compras.")
    return "\n\n".join(t)
def texto_menu(p): return "📅 *Tu menú (semana tipo, se repite hasta el día " + str(p["dias"]) + ")*\n\n" + _sec_sem(p)
def texto_lista(p): return _sec_lista(p)
def prompt_recetas(p):
    ing = ", ".join(i["nombre"].lower() for i in p["items"])
    rep = "; ".join(f"{ICONO[m]}: " + ", ".join(v["lineas"]) for m, v in p["comidas"].items())
    return (f"Con SOLO estos ingredientes: {ing} (más sal, especias y agua), escribe 5 recetas baratas, apetitosas y de preparación por lotes (se cocinan el domingo y se calientan entre semana en 10 minutos), "
            f"respetando estas porciones diarias: {rep}. Para cada receta: nombre, ingredientes con gramos por porción y 3 pasos cortos. Español, máximo 90 palabras por receta, sin consejos médicos.")
