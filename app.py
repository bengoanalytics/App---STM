"""
¿Cuánta gente sube? - Demanda por parada, línea y hora (STM Montevideo)

    streamlit run app.py

Día típico calculado con los boletos de marzo 2026 y los horarios programados.
"""

import re
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="¿Cuánta gente sube? | STM", page_icon="🚌", layout="wide",
                   initial_sidebar_state="collapsed")

BASE = Path(__file__).parent / "data"
ZONA = ZoneInfo("America/Montevideo")

TIPOS = ["habil", "sabado", "domingo"]
ETIQUETA_DIA = {"habil": "Día hábil", "sabado": "Sábado", "domingo": "Domingo / feriado"}

# Criterio de demanda: personas que suben por ómnibus respecto de su capacidad.
CAPACIDAD = 70        # pasajeros por ómnibus (supuesto del proyecto)
UMBRAL_MEDIA = 0.05   # desde 5 % de la capacidad -> media
UMBRAL_ALTA = 0.10    # desde 10 % de la capacidad -> alta
HORAS_ADELANTE = 4    # cuántas horas siguientes mira la recomendación

COLOR = {"baja": "#2F7A4C", "media": "#D99A2B", "alta": "#B53A22", "sin dato": "#9AA3AD"}
FONDO = {"baja": "#EAF4EE", "media": "#FBF3E4", "alta": "#FBEDEA", "sin dato": "#F1F2F4"}
TEXTO_SOBRE = {"baja": "#FFFFFF", "media": "#14181F", "alta": "#FFFFFF", "sin dato": "#FFFFFF"}
NOMBRE_NIVEL = {"baja": "Baja", "media": "Media", "alta": "Alta", "sin dato": "Sin dato"}
ORDEN = {"baja": 0, "media": 1, "alta": 2, "sin dato": 9}

# Feriados no laborables de fecha fija: se tratan como domingo.
FERIADOS = {(1, 1), (5, 1), (7, 18), (8, 25), (12, 25)}


# ------------------------------------------------------------------
# ESTILO
# ------------------------------------------------------------------

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stApp { font-family: Inter, system-ui, sans-serif; }
.stApp { background: #F4F5F7; }
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none; }
header[data-testid="stHeader"] { display: none; }
.block-container { padding-top: 0.5rem; max-width: 1180px; }
hr { margin: 0.4rem 0 !important; }
h1, h2, h3 { font-family: 'Space Grotesk', Inter, sans-serif !important; }
.cab { background: #14181F; color: #fff; border-radius: 0 0 16px 16px; padding: 18px 26px;
       display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.cab-t { font-family: 'Space Grotesk', Inter, sans-serif; font-size: 24px; font-weight: 600; line-height: 1.1; }
.cab-s { font-size: 13px; color: #C9CED6; }
.cab-ico { width: 48px; height: 48px; border-radius: 12px; background: #F2B705; display: flex;
           align-items: center; justify-content: center; flex: 0 0 auto; }
.tarjeta { background: #fff; border: 1px solid #E2E5EA; border-radius: 16px; padding: 22px 24px; }
.chip { display: inline-block; font-weight: 700; font-size: 13px; letter-spacing: .04em; padding: 5px 14px;
        border-radius: 999px; }
.titular { font-family: 'Space Grotesk', Inter, sans-serif; font-size: 34px; line-height: 1.15;
           font-weight: 600; margin: 14px 0 18px; color: #14181F; }
.dato { background: #F4F5F7; border-radius: 12px; padding: 12px 16px; }
.dato-l { font-size: 12px; color: #4A5260; }
.dato-v { font-size: 24px; font-weight: 700; color: #14181F; }
.esperar-t { font-family: 'Space Grotesk', Inter, sans-serif; font-size: 20px; font-weight: 600;
             line-height: 1.25; margin: 8px 0 12px; color: #14181F; }
.fila-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px;
          border-radius: 10px; margin-bottom: 8px; font-size: 13px; color: #4A5260; }
.nota { font-size: 12px; color: #5A6270; }
div[data-testid="stVerticalBlockBorderWrapper"] { background: #fff; border-radius: 16px; }
</style>
""", unsafe_allow_html=True)


def a_lista(valor):
    if isinstance(valor, list):
        return [float(v) for v in valor]
    return [float(v) for v in str(valor).strip("[]").split(",") if v.strip()]


def tipo_de_dia(momento: datetime) -> str:
    """Hábil / sábado / domingo según la fecha. El día de servicio arranca a las 4:00."""
    dia = (momento - timedelta(hours=4)).date()
    if (dia.month, dia.day) in FERIADOS:
        return "domingo"
    wd = dia.weekday()
    return "habil" if wd < 5 else ("sabado" if wd == 5 else "domingo")


def nombre_lindo(texto: str) -> str:
    """'PZA. ESPAÑA - LOS AROMOS' -> 'Pza. España – Los Aromos'."""
    t = " ".join(texto.split()).title().replace(" -- ", " – ").replace(" - ", " – ")
    # "de", "la", "y"... en minúscula salvo al inicio de un tramo (después de "–")
    return re.sub(r"(?<=[\w.]) (De|Del|La|Las|Los|Y|E)(?= )", lambda m: " " + m.group(1).lower(), t)


def num(x: float, dec: int = 1) -> str:
    """Número con coma decimal: 6.8 -> '6,8'."""
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calle(texto: str) -> str:
    t = nombre_lindo(str(texto))
    for a, b in [("Av ", "Av. "), ("Bv ", "Bv. "), ("Dr ", "Dr. "), ("Gral ", "Gral. "), ("Cno ", "Cno. "),
                 ("Ing ", "Ing. "), ("Cr ", "Cr. "), ("Dra ", "Dra. "), ("Ma ", "Ma. ")]:
        t = t.replace(a, b) if t.startswith(a) or f" {a}" in t else t
    return t


# ------------------------------------------------------------------
# DATOS
# ------------------------------------------------------------------

@st.cache_resource
def cargar():
    tabla = pd.read_csv(BASE / "tabla_variantes.csv.gz")
    paradas = pd.read_csv(BASE / "paradas.csv.gz", dtype={"clave": str})
    recorridos = pd.read_csv(BASE / "recorridos.csv.gz")
    tabla["carga"] = tabla["indice"] / CAPACIDAD
    tabla["nivel"] = np.select([tabla["carga"].isna(), tabla["carga"] >= UMBRAL_ALTA,
                                tabla["carga"] >= UMBRAL_MEDIA], ["sin dato", "alta", "media"], "baja")
    tabla["codigo_parada"] = tabla["codigo_parada_origen"].astype(int)
    tabla["variante"] = tabla["sevar_codigo"].astype(int)
    tabla["linea"] = tabla["linea"].astype(str)
    tabla["sublinea"] = tabla["sublinea"].fillna("").astype(str).map(nombre_lindo)
    tabla["etiqueta"] = tabla["linea"] + " → " + tabla["sublinea"]
    paradas["codigo_parada"] = paradas["clave"].astype(int)
    return tabla, paradas, recorridos


TABLA, PARADAS, RECORRIDOS = cargar()
DIRECCION = {int(f.codigo_parada): f"{calle(f.CALLE)} y {calle(f.ESQUINA)}" for f in PARADAS.itertuples()}


def _click_mapa():
    """Al tocar una parada en el mapa, la selecciona."""
    try:
        puntos = st.session_state["mapa"]["selection"]["points"]
    except Exception:
        return
    if puntos:
        cd = puntos[0].get("customdata")
        codigo = cd[0] if isinstance(cd, (list, tuple)) else cd
        if codigo is not None and int(codigo) in DIRECCION:
            st.session_state["parada"] = int(codigo)


# ------------------------------------------------------------------
# ENCABEZADO
# ------------------------------------------------------------------

st.markdown("""
<div class="cab">
  <div style="display:flex;align-items:center;gap:14px">
    <div class="cab-ico"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#14181F" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="14" rx="3"/><path d="M4 11h16M7 7h10M7 21v-4M17 21v-4"/></svg></div>
    <div><div class="cab-t">¿Cuánta gente sube?</div>
    <div class="cab-s">Ómnibus de Montevideo · día típico con datos de marzo 2026</div></div>
  </div>
  <svg width="170" height="44" viewBox="0 0 170 44" aria-hidden="true">
    <path d="M0 40 H170" stroke="#3A414D" stroke-width="2" stroke-dasharray="8 7"/>
    <path d="M6 14 H30 M0 22 H26 M10 30 H32" stroke="#5A6270" stroke-width="2" stroke-linecap="round"/>
    <rect x="40" y="4" width="122" height="30" rx="8" fill="#F2B705"/>
    <rect x="48" y="10" width="18" height="12" rx="2" fill="#14181F"/><rect x="71" y="10" width="18" height="12" rx="2" fill="#14181F"/>
    <rect x="94" y="10" width="18" height="12" rx="2" fill="#14181F"/><rect x="117" y="10" width="18" height="12" rx="2" fill="#14181F"/>
    <rect x="140" y="10" width="16" height="20" rx="2" fill="#14181F"/>
    <circle cx="66" cy="35" r="5" fill="#14181F" stroke="#C9CED6" stroke-width="2"/>
    <circle cx="136" cy="35" r="5" fill="#14181F" stroke="#C9CED6" stroke-width="2"/>
  </svg>
</div>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------
# ELECCIÓN: PARADA, LÍNEA, DÍA Y HORA
# ------------------------------------------------------------------

AHORA = datetime.now(ZONA)
with st.container(border=True):
    c1, c2 = st.columns(2)
    # El tipo de día y la hora se definen primero para ordenar las paradas, pero se muestran abajo.
    usar_ahora = st.session_state.get("ahora", True)
    if usar_ahora:
        tipo_dia, hora = tipo_de_dia(AHORA), AHORA.hour
    else:
        tipo_dia = st.session_state.get("tipo_dia", tipo_de_dia(AHORA))
        hora = st.session_state.get("hora", AHORA.hour)

    DIA = TABLA[TABLA.tipo_dia == tipo_dia]
    TOTAL_PARADA = (DIA.drop_duplicates(["codigo_parada", "hora"]).groupby("codigo_parada")["total_parada"]
                    .sum().sort_values(ascending=False))
    codigos = [c for c in TOTAL_PARADA.index if c in DIRECCION]
    if st.session_state.get("parada") not in codigos:
        st.session_state["parada"] = codigos[0]
    codigo_parada = c1.selectbox("📍 Parada", codigos, key="parada",
                                 format_func=lambda c: f"{DIRECCION[c]} · {c}")

    vars_parada = (DIA[DIA.codigo_parada == codigo_parada].groupby(["variante", "etiqueta"], as_index=False)
                   ["ascensos_tipicos"].sum().sort_values("ascensos_tipicos", ascending=False))
    opciones_var = vars_parada["variante"].tolist()
    etiqueta_var = dict(zip(vars_parada["variante"], vars_parada["etiqueta"]))
    if st.session_state.get("variante") not in opciones_var:
        st.session_state["variante"] = opciones_var[0]
    variante = c2.selectbox("🚌 Línea y destino", opciones_var, key="variante",
                            format_func=lambda v: etiqueta_var[v])

    t1, t2 = st.columns([1, 4], vertical_alignment="center")
    t1.toggle("Ahora", value=True, key="ahora")
    if st.session_state["ahora"]:
        t2.caption(f"{ETIQUETA_DIA[tipo_dia]} · {hora:02d}:00 — se actualiza solo")
    else:
        d1, d2, _ = t2.columns([1, 1, 1])
        d1.selectbox("Tipo de día", TIPOS, key="tipo_dia", format_func=ETIQUETA_DIA.get,
                     index=TIPOS.index(tipo_de_dia(AHORA)))
        d2.selectbox("Hora", list(range(24)), key="hora", index=AHORA.hour, format_func=lambda h: f"{h:02d}:00")

fila_var = DIA[(DIA.codigo_parada == codigo_parada) & (DIA.variante == variante)]
linea = str(fila_var["linea"].iloc[0]) if not fila_var.empty else ""
sublinea = str(fila_var["sublinea"].iloc[0]) if not fila_var.empty else ""

perfil = fila_var.set_index("hora").reindex(range(24))
perfil["ascensos_tipicos"] = perfil["ascensos_tipicos"].fillna(0)
perfil["salidas"] = perfil["salidas"].fillna(0)
perfil["nivel"] = perfil["nivel"].fillna("sin dato")

f = perfil.loc[hora]
nivel = str(f["nivel"])
indice = None if pd.isna(f["indice"]) else float(f["indice"])
ascensos = float(f["ascensos_tipicos"])
salidas = int(f["salidas"])
pct_parada = None if pd.isna(f.get("pct_parada")) else float(f["pct_parada"])
carga = None if indice is None else indice / CAPACIDAD


# ------------------------------------------------------------------
# RESULTADO + SI PODÉS ESPERAR
# ------------------------------------------------------------------

def bus_frente(nivel: str, linea: str, destino: str, carga) -> str:
    """Ómnibus de frente: el cartel muestra la línea y el destino; el parabrisas, el nivel."""
    col = COLOR[nivel]
    txt = TEXTO_SOBRE[nivel]
    destino = escape(destino.split(" – ")[0][:20])
    pct1 = "" if carga is None else f"{carga:.0%} de la capacidad total"
    pct2 = "" if carga is None else "sube en esta parada"
    titulo = "Sin ómnibus" if nivel == "sin dato" else f"Demanda {nivel}"
    return f"""
<svg role="img" aria-label="Ómnibus de frente, línea {escape(linea)}: {titulo}" viewBox="0 0 300 300"
     style="width:100%;max-width:250px;height:auto">
  <ellipse cx="150" cy="290" rx="120" ry="7" fill="#14181F" opacity="0.15"/>
  <rect x="44" y="246" width="40" height="38" rx="7" fill="#1B1F26"/>
  <rect x="216" y="246" width="40" height="38" rx="7" fill="#1B1F26"/>
  <rect x="20" y="12" width="260" height="254" rx="24" fill="#E4E7EC" stroke="#C9CED6" stroke-width="2"/>
  <rect x="34" y="24" width="232" height="44" rx="6" fill="#0E1116"/>
  <text x="48" y="56" font-family="Space Grotesk, Inter, sans-serif" font-size="28" font-weight="700" fill="#FFFFFF">{escape(linea)}</text>
  <text x="{56 + 17 * len(linea)}" y="54" font-family="Inter, sans-serif" font-size="15" font-weight="600" fill="#FFFFFF">{destino}</text>
  <rect x="34" y="80" width="232" height="120" rx="4" fill="{col}"/>
  <text x="150" y="134" text-anchor="middle" font-family="Inter, sans-serif" font-size="20" font-weight="700" fill="{txt}">{titulo}</text>
  <text x="150" y="160" text-anchor="middle" font-family="Inter, sans-serif" font-size="13" fill="{txt}">{pct1}</text>
  <text x="150" y="177" text-anchor="middle" font-family="Inter, sans-serif" font-size="13" fill="{txt}">{pct2}</text>
  <rect x="34" y="200" width="232" height="8" fill="#14181F"/>
  <rect x="52" y="222" width="46" height="18" rx="9" fill="#FFF4C2"/>
  <rect x="202" y="222" width="46" height="18" rx="9" fill="#FFF4C2"/>
</svg>"""


def leyenda() -> str:
    filas = [("alta", "Alta", f"{UMBRAL_ALTA:.0%} o más"),
             ("media", "Media", f"{UMBRAL_MEDIA:.0%} a {UMBRAL_ALTA:.0%}"),
             ("baja", "Baja", f"menos de {UMBRAL_MEDIA:.0%}")]
    cajas = "".join(
        f"<div style='display:flex;background:{FONDO[k]};border-radius:4px;margin-bottom:3px'>"
        f"<div style='width:8px;background:{COLOR[k]};border-radius:4px 0 0 4px'></div>"
        f"<div style='padding:6px 10px;font-size:12px;color:#14181F'><b>{n}</b><br>{r}</div></div>"
        for k, n, r in filas)
    return (f"<div style='font-size:13px;color:#4A5260;margin-bottom:8px'>La <b>demanda</b> se calcula en función "
            f"de la capacidad total del ómnibus ({CAPACIDAD} pasajeros).</div>{cajas}")


col_res, col_esp = st.columns([2.2, 1], gap="medium")

with col_res:
    if nivel == "sin dato":
        titular = "No hay ómnibus de esta línea programados a esta hora"
    else:
        titular = (f"Suben unas <span style='color:{COLOR[nivel]}'>{indice:.0f} personas</span> "
                   f"por ómnibus en esta parada")
    chip = (f"<span class='chip' style='background:{COLOR[nivel]};color:{TEXTO_SOBRE[nivel]}'>"
            f"{'SIN DATO' if nivel == 'sin dato' else 'DEMANDA ' + nivel.upper()}</span>")
    contexto = escape(f"{linea} → {sublinea} · {DIRECCION[codigo_parada]}")
    datos = "".join(
        f"<div class='dato'><div class='dato-l'>{l}</div><div class='dato-v'>{v}</div></div>"
        for l, v in [("Personas por hora", num(ascensos, 0)),
                     ("Ómnibus en esta hora", f"{salidas}"),
                     ("De la gente de la parada", "—" if pct_parada is None else f"{pct_parada:.0f}%")])
    st.markdown(f"""
<div class="tarjeta" style="border-top:6px solid {COLOR[nivel]}">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">{chip}
    <span style="font-size:13px;color:#4A5260">{contexto}</span></div>
  <div class="titular">{titular}</div>
  <div style="display:flex;align-items:center;gap:28px;flex-wrap:wrap;margin-bottom:18px">
    <div style="flex:0 0 250px">{bus_frente(nivel, linea, sublinea, carga)}</div>
    <div style="flex:1 1 200px;max-width:280px">{leyenda()}</div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px">{datos}</div>
</div>""", unsafe_allow_html=True)

with col_esp:
    siguientes = [h for h in range(hora + 1, min(hora + 1 + HORAS_ADELANTE, 24))]
    filas = ""
    for h in siguientes:
        p = perfil.loc[h]
        n = str(p["nivel"])
        detalle = ("sin ómnibus" if n == "sin dato"
                   else f"{num(p['indice'])} por ómnibus · {int(p['salidas'])} ómnibus")
        filas += (f"<div class='fila-h' style='background:{FONDO[n]}'><b style='color:#14181F;font-size:15px'>"
                  f"{h:02d}:00</b><span>{detalle}</span><span class='chip' style='font-size:11px;padding:3px 10px;"
                  f"background:{COLOR[n]};color:{TEXTO_SOBRE[n]}'>{NOMBRE_NIVEL[n]}</span></div>")

    mejor = [h for h in siguientes if perfil.loc[h, "nivel"] != "sin dato"
             and ORDEN[perfil.loc[h, "nivel"]] < ORDEN.get(nivel, 9)]
    if nivel == "sin dato":
        mensaje = "A esta hora no hay ómnibus de esta línea programados"
    elif nivel == "baja":
        mensaje = "Buen momento para viajar: la demanda es baja"
    elif mejor:
        h = mejor[0]
        mensaje = (f"A las {h:02d}:00 baja a {perfil.loc[h, 'nivel']}: unas "
                   f"{num(perfil.loc[h, 'indice'])} personas por ómnibus")
    elif not siguientes:
        mensaje = "Es la última hora del día de servicio"
    else:
        mensaje = "En las próximas horas la demanda sigue igual o sube"

    st.markdown(f"""
<div class="tarjeta" style="height:100%">
  <div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:#4A5260;letter-spacing:.05em">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4A5260" stroke-width="2" stroke-linecap="round">
    <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>SI PODÉS ESPERAR</div>
  <div class="esperar-t">{mensaje}</div>
  {filas}
  <div class="nota">Solo las horas siguientes, mismo destino.</div>
</div>""", unsafe_allow_html=True)

st.write("")


# ------------------------------------------------------------------
# CÓMO SE MUEVE EL DÍA
# ------------------------------------------------------------------

with st.container(border=True):
    st.markdown("#### Cómo se mueve el día")
    st.caption("Barras: personas que suben por ómnibus (color = nivel). Línea: ómnibus por hora. "
               "Debajo de cada hora, la cantidad de ómnibus programados.")
    horas = list(range(24))
    y = perfil["indice"].fillna(0)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=horas, y=y, name="Personas por ómnibus",
        marker=dict(color=[COLOR[n] for n in perfil["nivel"]],
                    line=dict(color="#14181F", width=[3 if h == hora else 0 for h in horas])),
        customdata=np.stack([perfil["ascensos_tipicos"], perfil["salidas"],
                             [NOMBRE_NIVEL[n] for n in perfil["nivel"]]], axis=-1),
        hovertemplate=("%{x}:00 · %{customdata[2]}<br>%{y:.1f} personas por ómnibus"
                       "<br>%{customdata[0]:.0f} personas por hora · %{customdata[1]} ómnibus<extra></extra>")))
    fig.add_trace(go.Scatter(
        x=horas, y=perfil["salidas"], name="Ómnibus por hora", yaxis="y2", mode="lines",
        line=dict(color="#14181F", width=2), hovertemplate="%{x}:00 · %{y:.0f} ómnibus<extra></extra>"))
    ticks = [f"{h}<br><b>{int(s) if s else '–'}</b>" for h, s in zip(horas, perfil["salidas"])]
    fig.update_layout(
        xaxis=dict(tickmode="array", tickvals=horas, ticktext=ticks, title="Hora / ómnibus"),
        yaxis=dict(title="Personas por ómnibus", gridcolor="#ECEEF2"),
        yaxis2=dict(title="Ómnibus por hora", overlaying="y", side="right", showgrid=False, rangemode="tozero",
                    tickformat="d", dtick=2),
        height=380, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        showlegend=False, bargap=0.18, font=dict(family="Inter, sans-serif"))
    st.plotly_chart(fig, width="stretch")


# ------------------------------------------------------------------
# DÓNDE QUEDA LA PARADA
# ------------------------------------------------------------------

with st.container(border=True):
    st.markdown(f"#### Dónde queda la parada")
    st.caption(f"{DIRECCION[codigo_parada]} · tocá otra parada gris para cambiarla")
    top = PARADAS.set_index("codigo_parada").loc[codigos]
    sel = PARADAS[PARADAS.codigo_parada == codigo_parada].iloc[0]
    fig_mapa = go.Figure()
    ruta = RECORRIDOS[(RECORRIDOS.codigo_parada == codigo_parada) & (RECORRIDOS.sevar_codigo == variante)]
    if not ruta.empty:
        r = ruta.iloc[0]
        fig_mapa.add_trace(go.Scattermap(
            lat=a_lista(r["lat"]), lon=a_lista(r["lon"]), mode="lines", hoverinfo="skip",
            name="Recorrido de la línea", line=dict(width=5, color="#1F4FA8")))
    fig_mapa.add_trace(go.Scattermap(
        lat=top["lat"], lon=top["lon"], mode="markers", name="Otras paradas principales",
        marker=dict(size=11, color="#8A929E"), customdata=[[c_] for c_ in top.index],
        text=[f"{DIRECCION[c_]} · {c_}" for c_ in top.index], hovertemplate="%{text}<extra></extra>"))
    fig_mapa.add_trace(go.Scattermap(
        lat=[float(sel["lat"])], lon=[float(sel["lon"])], mode="markers+text", name="Parada elegida",
        marker=dict(size=24, color=COLOR[nivel]), customdata=[[codigo_parada]],
        text=[f"  {DIRECCION[codigo_parada]}"], textposition="middle right",
        textfont=dict(size=14, color="#14181F"), hovertemplate="%{text}<extra></extra>"))
    fig_mapa.update_layout(
        map=dict(style="carto-positron", zoom=11.6,
                 center=dict(lat=(float(sel["lat"]) - 34.880) / 2, lon=(float(sel["lon"]) - 56.170) / 2)),
        height=520, margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h", y=0.01, x=0.01, bgcolor="rgba(255,255,255,0.85)"))
    st.plotly_chart(fig_mapa, width="stretch", key="mapa", on_select=_click_mapa, selection_mode="points")


# ------------------------------------------------------------------
# MÁS DETALLE
# ------------------------------------------------------------------

with st.expander(f"Quién más sube en esta parada a las {hora:02d}:00"):
    reparto = (DIA[(DIA.codigo_parada == codigo_parada) & (DIA.hora == hora)]
               [["etiqueta", "ascensos_tipicos", "pct_parada", "salidas", "indice", "nivel"]]
               .sort_values("pct_parada", ascending=False)
               .rename(columns={"etiqueta": "Línea y destino", "ascensos_tipicos": "Personas por hora",
                                "pct_parada": "% de la parada", "salidas": "Ómnibus",
                                "indice": "Personas por ómnibus", "nivel": "Nivel"}))
    st.dataframe(reparto, hide_index=True, width="stretch",
                 column_config={"Personas por hora": st.column_config.NumberColumn(format="%.0f"),
                                "% de la parada": st.column_config.NumberColumn(format="%.0f %%"),
                                "Personas por ómnibus": st.column_config.NumberColumn(format="%.1f")})
    resto = 100 - reparto["% de la parada"].fillna(0).sum()
    st.caption(f"El {max(resto, 0):.0f} % restante sube a otras líneas o variantes menos usadas en esta parada.")

with st.expander("Mapa de calor de la parada"):
    mat = (DIA[DIA.codigo_parada == codigo_parada]
           .pivot_table(index="etiqueta", columns="hora", values="ascensos_tipicos", aggfunc="sum")
           .reindex(columns=range(24)).fillna(0))
    mat = mat.loc[mat.sum(axis=1).sort_values(ascending=True).index]
    fig_h = go.Figure(go.Heatmap(
        z=mat.values, x=[f"{h:02d}" for h in range(24)], y=mat.index, colorscale="YlOrRd",
        colorbar=dict(title="Personas<br>por hora"), hovertemplate="%{y}<br>%{x}:00 · %{z:,.0f} personas<extra></extra>"))
    fig_h.update_layout(height=120 + 45 * len(mat), margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig_h, width="stretch")

with st.expander("Cómo se calcula el nivel"):
    st.markdown(
        f"- Se toman los boletos de marzo 2026 y se calcula un **día típico** (hábil, sábado o domingo) "
        f"para cada parada, línea y destino, y hora.\n"
        f"- Esas personas se dividen entre los **ómnibus programados** en esa hora: así se obtienen las "
        f"**personas que suben por ómnibus**.\n"
        f"- Ese número se compara con la **capacidad de un ómnibus ({CAPACIDAD} pasajeros)**: "
        f"baja menos de {UMBRAL_MEDIA:.0%}, media de {UMBRAL_MEDIA:.0%} a {UMBRAL_ALTA:.0%} y alta desde "
        f"{UMBRAL_ALTA:.0%}.\n"
        f"- Mide lo que se suma **en esta parada**. No incluye a quienes ya vienen a bordo desde paradas anteriores.")

st.markdown("<p class='nota' style='margin-top:16px'>Mide la gente que sube en esta parada por cada ómnibus "
            "programado. No incluye a quienes ya vienen a bordo. Datos: boletos STM de marzo 2026 y horarios "
            "programados.</p>", unsafe_allow_html=True)
