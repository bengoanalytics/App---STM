"""
Streamlit - Demanda por parada, variante y hora (STM)

    streamlit run app.py

Consume la API local; si no esta corriendo, funciona igual con los CSV.
"""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="STM | Demanda por parada y hora", page_icon="🚌", layout="wide")

BASE = Path(__file__).parent / "data"
API = "http://127.0.0.1:8000"
ZONA = ZoneInfo("America/Montevideo")

TIPOS = ["habil", "sabado", "domingo"]
ETIQUETA_DIA = {"habil": "Día hábil", "sabado": "Sábado", "domingo": "Domingo / feriado"}
COLOR_NIVEL = {"baja": "#2e9e5b", "media": "#e9a23b", "alta": "#d64545", "sin dato": "#9aa3ad"}
TEXTO_NIVEL = {"baja": "Demanda baja", "media": "Demanda media", "alta": "Demanda alta",
               "sin dato": "Sin ómnibus programado"}
# Criterio de demanda: personas que suben por omnibus respecto de su capacidad.
CAPACIDAD = 70        # pasajeros por omnibus (supuesto del proyecto)
UMBRAL_MEDIA = 0.15   # desde 15 % de la capacidad -> media
UMBRAL_ALTA = 0.30    # desde 30 % de la capacidad -> alta
ORDEN = {"baja": 0, "media": 1, "alta": 2, "sin dato": 9}
# Feriados no laborables de fecha fija: se tratan como domingo. VERIFICAR / completar.
FERIADOS = {(1, 1), (5, 1), (7, 18), (8, 25), (12, 25)}


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


def badge(nivel: str) -> str:
    return (f"<span style='background:{COLOR_NIVEL[nivel]};color:white;padding:4px 12px;"
            f"border-radius:12px;font-weight:600'>{TEXTO_NIVEL[nivel]}</span>")


# ------------------------------------------------------------------
# DATOS
# ------------------------------------------------------------------

@st.cache_resource
def cargar_local():
    tabla = pd.read_csv(BASE / "tabla_variantes.csv.gz")
    paradas = pd.read_csv(BASE / "paradas.csv.gz", dtype={"clave": str})
    recorridos = pd.read_csv(BASE / "recorridos.csv.gz")
    # nivel segun capacidad del omnibus (reemplaza el nivel por terciles de la tabla)
    tabla["carga"] = tabla["indice"] / CAPACIDAD
    tabla["nivel"] = np.select([tabla["carga"].isna(), tabla["carga"] >= UMBRAL_ALTA,
                                tabla["carga"] >= UMBRAL_MEDIA], ["sin dato", "alta", "media"], "baja")
    tabla["codigo_parada"] = tabla["codigo_parada_origen"].astype(int)
    tabla["variante"] = tabla["sevar_codigo"].astype(int)
    tabla["linea"] = tabla["linea"].astype(str)
    tabla["sublinea"] = tabla["sublinea"].fillna("").astype(str)
    tabla["etiqueta"] = tabla["linea"] + " · " + tabla["sublinea"]
    paradas["codigo_parada"] = paradas["clave"].astype(int)
    return tabla, paradas, recorridos


@st.cache_resource
def api_disponible():
    try:
        requests.get(f"{API}/health", timeout=2)
        return True
    except Exception:
        return False


TABLA, PARADAS, RECORRIDOS = cargar_local()
CON_API = api_disponible()
NOMBRE_PARADA = {int(f.codigo_parada): f"{int(f.codigo_parada)} - {f.CALLE} y {f.ESQUINA}"
                 for f in PARADAS.itertuples()}


def consultar(parada: int, variante: int, hora: int, tipo_dia: str) -> dict:
    """Consulta la API; si no responde, lee la tabla local."""
    if CON_API:
        try:
            r = requests.get(f"{API}/api/ascensos", timeout=5, params={
                "codigo_parada": parada, "variante": variante, "hora": hora, "tipo_dia": tipo_dia})
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    f = TABLA[(TABLA.codigo_parada == parada) & (TABLA.variante == variante)
              & (TABLA.tipo_dia == tipo_dia) & (TABLA.hora == hora)]
    if f.empty:
        return {"ascensos": 0.0, "pct_parada": None, "salidas": 0, "indice": None, "nivel": "sin dato"}
    f = f.iloc[0]
    return {"ascensos": float(f.ascensos_tipicos),
            "pct_parada": None if pd.isna(f.pct_parada) else float(f.pct_parada),
            "salidas": int(f.salidas),
            "indice": None if pd.isna(f.indice) else float(f.indice),
            "nivel": str(f.nivel)}


def _click_mapa():
    """Al tocar una parada en el mapa, la selecciona en la barra lateral."""
    try:
        puntos = st.session_state["mapa"]["selection"]["points"]
    except Exception:
        return
    if puntos:
        cd = puntos[0].get("customdata")
        codigo = cd[0] if isinstance(cd, (list, tuple)) else cd
        if codigo is not None and int(codigo) in NOMBRE_PARADA:
            st.session_state["parada"] = int(codigo)


# ------------------------------------------------------------------
# BARRA LATERAL
# ------------------------------------------------------------------

st.sidebar.markdown("## Estado")
if CON_API:
    st.sidebar.success("API conectada")
else:
    st.sidebar.info("API no disponible: usando los CSV locales")

st.sidebar.markdown("---")
st.sidebar.markdown("## Cuándo")
AHORA = datetime.now(ZONA)
if st.sidebar.toggle("Usar día y hora actuales", value=True):
    tipo_dia, hora = tipo_de_dia(AHORA), AHORA.hour
    st.sidebar.caption(f"Ahora: {ETIQUETA_DIA[tipo_dia]} · {hora:02d}h")
else:
    tipo_dia = st.sidebar.radio("Tipo de día", TIPOS, format_func=ETIQUETA_DIA.get,
                                index=TIPOS.index(tipo_de_dia(AHORA)))
    hora = st.sidebar.slider("Hora del día", 0, 23, AHORA.hour)

DIA = TABLA[TABLA.tipo_dia == tipo_dia]
TOTAL_PARADA = (DIA.drop_duplicates(["codigo_parada", "hora"]).groupby("codigo_parada")["total_parada"].sum()
                .sort_values(ascending=False))

st.sidebar.markdown("## Dónde")
codigos = [c for c in TOTAL_PARADA.index if c in NOMBRE_PARADA]
if st.session_state.get("parada") not in codigos:
    st.session_state["parada"] = codigos[0]
codigo_parada = st.sidebar.selectbox(
    "Parada (también podés tocarla en el mapa)", codigos, key="parada",
    format_func=lambda c: f"{NOMBRE_PARADA[c]} ({TOTAL_PARADA[c]:,.0f}/día)")

vars_parada = (DIA[DIA.codigo_parada == codigo_parada].groupby(["variante", "etiqueta"], as_index=False)
               ["ascensos_tipicos"].sum().sort_values("ascensos_tipicos", ascending=False))
opciones_var = vars_parada["variante"].tolist()
etiqueta_var = dict(zip(vars_parada["variante"], vars_parada["etiqueta"]))
if st.session_state.get("variante") not in opciones_var:
    st.session_state["variante"] = opciones_var[0]
variante = st.sidebar.selectbox("Línea y destino", opciones_var, key="variante",
                                format_func=lambda v: etiqueta_var[v])
etiqueta = etiqueta_var[variante]


# ------------------------------------------------------------------
# TITULO Y METRICAS
# ------------------------------------------------------------------

st.title("🚌 Demanda por parada, línea y hora")
st.caption("Sistema de Transporte Metropolitano · Montevideo · día típico calculado con boletos de marzo 2026 "
           "y horarios programados del STM")

datos = consultar(codigo_parada, variante, hora, tipo_dia)
st.markdown(f"**{etiqueta}** · {NOMBRE_PARADA[codigo_parada]} · {ETIQUETA_DIA[tipo_dia]}, {hora:02d}h "
            f"&nbsp;&nbsp; {badge(datos['nivel'])}", unsafe_allow_html=True)

perfil = (DIA[(DIA.codigo_parada == codigo_parada) & (DIA.variante == variante)]
          .set_index("hora").reindex(range(24)))
perfil["ascensos_tipicos"] = perfil["ascensos_tipicos"].fillna(0)
perfil["salidas"] = perfil["salidas"].fillna(0)
perfil["nivel"] = perfil["nivel"].fillna("sin dato")

c = st.columns(6)
c[0].metric("Personas que suben", f"{datos['ascensos']:,.0f}", help="En esa hora, en un día típico")
c[1].metric("% de la parada", "—" if datos["pct_parada"] is None else f"{datos['pct_parada']:.0f} %",
            help="De toda la gente que sube en esta parada a esa hora, cuántos toman esta línea y destino")
c[2].metric("Ómnibus programados", f"{datos['salidas']}")
c[3].metric("Personas por ómnibus", "—" if datos["indice"] is None else f"{datos['indice']:.1f}",
            help=f"Equivale a {datos['indice'] / CAPACIDAD:.0%} de la capacidad de un ómnibus ({CAPACIDAD} pasajeros)"
            if datos["indice"] is not None else None)
c[4].metric("Total del día", f"{perfil['ascensos_tipicos'].sum():,.0f}")
pico = int(perfil["ascensos_tipicos"].idxmax())
c[5].metric("Hora pico", f"{pico:02d}h · {perfil['ascensos_tipicos'].max():,.0f}")


# ------------------------------------------------------------------
# MAPA CENTRAL
# ------------------------------------------------------------------

st.subheader("Mapa")
st.caption("Gris: las 20 paradas con más pasajeros (tamaño = pasajeros por día). "
           "Naranja: dónde se sube más gente a esta línea y destino. "
           "Estrella: la parada elegida, con el color de su nivel de demanda.")

pts = PARADAS.set_index("codigo_parada").loc[codigos]
ranking = (DIA[DIA.variante == variante].groupby("codigo_parada")["ascensos_tipicos"].sum()
           .sort_values(ascending=False))
rk = PARADAS.set_index("codigo_parada").loc[[p for p in ranking.index if p in NOMBRE_PARADA]]
escala = lambda s, a, b: a + (b - a) * (s - s.min()) / ((s.max() - s.min()) or 1)

fig_mapa = go.Figure()
ruta = RECORRIDOS[(RECORRIDOS.codigo_parada == codigo_parada) & (RECORRIDOS.sevar_codigo == variante)]
if not ruta.empty:
    r = ruta.iloc[0]
    fig_mapa.add_trace(go.Scattermap(
        lat=a_lista(r["lat"]), lon=a_lista(r["lon"]), mode="lines", hoverinfo="skip",
        name="Recorrido" + ("" if bool(r["exacto"]) else " (aprox.)"), line=dict(width=4, color="royalblue")))
fig_mapa.add_trace(go.Scattermap(
    lat=pts["lat"], lon=pts["lon"], mode="markers", name="Top 20 paradas",
    marker=dict(size=escala(TOTAL_PARADA.loc[codigos], 9, 22), color="#6c757d", opacity=0.55),
    customdata=[[c_] for c_ in pts.index], text=[NOMBRE_PARADA[c_] for c_ in pts.index],
    hovertemplate="%{text}<br>%{customdata[0]}<extra></extra>"))
if not rk.empty:
    fig_mapa.add_trace(go.Scattermap(
        lat=rk["lat"], lon=rk["lon"], mode="markers", name="Dónde se sube más gente a esta línea",
        marker=dict(size=escala(ranking.loc[rk.index], 8, 26), color="#f28e2b", opacity=0.85),
        customdata=[[c_] for c_ in rk.index],
        text=[f"{NOMBRE_PARADA[c_]}<br>{ranking[c_]:,.0f} personas/día a esta línea" for c_ in rk.index],
        hovertemplate="%{text}<extra></extra>"))
sel = PARADAS[PARADAS.codigo_parada == codigo_parada]
if not sel.empty:
    fig_mapa.add_trace(go.Scattermap(
        lat=[float(sel.iloc[0]["lat"])], lon=[float(sel.iloc[0]["lon"])], mode="markers+text",
        name="Parada elegida", text=[f"Parada {codigo_parada}"], textposition="top center",
        customdata=[[codigo_parada]], hovertemplate="%{text}<extra></extra>",
        marker=dict(size=22, color=COLOR_NIVEL[datos["nivel"]], symbol="star")))
fig_mapa.update_layout(
    map=dict(style="open-street-map", zoom=12,
             center=dict(lat=float(pts["lat"].mean()), lon=float(pts["lon"].mean()))),
    height=520, margin=dict(l=0, r=0, t=0, b=0),
    legend=dict(orientation="h", y=0.01, x=0.01, bgcolor="rgba(255,255,255,0.8)"))
st.plotly_chart(fig_mapa, width="stretch", key="mapa", on_select=_click_mapa, selection_mode="points")


# ------------------------------------------------------------------
# PESTAÑAS
# ------------------------------------------------------------------

t1, t2, t3, t4 = st.tabs(["Perfil horario", "Mapa de calor de la parada",
                          "Cómo se reparte la parada", "Dónde se sube más gente"])

with t1:
    horas = [f"{h:02d}h" for h in range(24)]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=horas, y=perfil["ascensos_tipicos"], name="Personas que suben",
        marker=dict(color=[COLOR_NIVEL[n] for n in perfil["nivel"]],
                    line=dict(color="black", width=[3 if h == hora else 0.4 for h in range(24)])),
        customdata=perfil[["salidas", "indice", "nivel"]].values,
        hovertemplate=("%{x}<br>Personas: %{y:,.0f}<br>Ómnibus: %{customdata[0]:.0f}"
                       "<br>Por ómnibus: %{customdata[1]:.1f}<br>%{customdata[2]}<extra></extra>")))
    fig.add_trace(go.Scatter(
        x=horas, y=perfil["salidas"], name="Ómnibus programados", yaxis="y2", mode="lines+markers",
        line=dict(color="#3b5b92", width=2), marker=dict(size=5),
        hovertemplate="%{x}<br>Ómnibus: %{y:.0f}<extra></extra>"))
    fig.update_layout(
        title="Color de cada barra = nivel de demanda por ómnibus · borde grueso = hora elegida",
        xaxis_title="Hora", yaxis=dict(title="Personas que suben"),
        yaxis2=dict(title="Ómnibus por hora", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
        height=430, margin=dict(l=0, r=0, t=40, b=0), legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch")

with t2:
    mat = (DIA[DIA.codigo_parada == codigo_parada]
           .pivot_table(index="etiqueta", columns="hora", values="ascensos_tipicos", aggfunc="sum")
           .reindex(columns=range(24)).fillna(0))
    mat = mat.loc[mat.sum(axis=1).sort_values(ascending=True).index]
    fig_h = go.Figure(go.Heatmap(
        z=mat.values, x=[f"{h:02d}h" for h in range(24)], y=mat.index, colorscale="YlOrRd",
        colorbar=dict(title="Personas"), hovertemplate="%{y}<br>%{x}: %{z:,.1f} personas<extra></extra>"))
    fig_h.update_layout(title=f"Personas que suben por hora · {NOMBRE_PARADA[codigo_parada]}",
                        height=120 + 45 * len(mat), margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig_h, width="stretch")

with t3:
    reparto = (DIA[(DIA.codigo_parada == codigo_parada) & (DIA.hora == hora)]
               [["etiqueta", "ascensos_tipicos", "pct_parada", "salidas", "indice", "nivel"]]
               .sort_values("pct_parada", ascending=False)
               .rename(columns={"etiqueta": "Línea y destino", "ascensos_tipicos": "Personas que suben",
                                "pct_parada": "% de la parada", "salidas": "Ómnibus",
                                "indice": "Personas por ómnibus", "nivel": "Nivel"}))
    st.markdown(f"A las **{hora:02d}h**, de cada 100 personas que suben en esta parada:")
    st.dataframe(reparto, hide_index=True, width="stretch")
    resto = 100 - reparto["% de la parada"].fillna(0).sum()
    st.caption(f"El {max(resto, 0):.0f} % restante sube a otras líneas o variantes menos usadas en esta parada.")

with t4:
    rank_df = ranking.rename("Personas por día").to_frame()
    rank_df.index = [NOMBRE_PARADA.get(p, str(p)) for p in rank_df.index]
    st.bar_chart(rank_df)


# ------------------------------------------------------------------
# RECOMENDACION (misma línea y destino, otra hora)
# ------------------------------------------------------------------

st.subheader("Recomendación")
nivel_actual = datos["nivel"]
cerca = perfil.reset_index()
cerca = cerca[(cerca.hora != hora) & cerca.hora.between(hora - 2, hora + 2) & cerca.indice.notna()
              & cerca.nivel.map(ORDEN).lt(ORDEN.get(nivel_actual, 9))].sort_values("indice")

if nivel_actual == "baja":
    st.success(f"A las {hora:02d}h esta línea suele tener poca demanda en esta parada. Buen momento para viajar.")
elif nivel_actual == "sin dato":
    st.info("No hay ómnibus de esta línea y destino programados en esa hora para esta parada.")
elif not cerca.empty:
    h = int(cerca.iloc[0].hora)
    st.info(f"🕒 Si podés, viajá a las **{h:02d}h**: con el mismo destino, la demanda suele ser "
            f"**{cerca.iloc[0].nivel}** ({cerca.iloc[0].indice:.1f} personas por ómnibus, "
            f"contra {datos['indice']:.1f} a las {hora:02d}h).")
else:
    st.warning("Las horas cercanas tienen una demanda parecida o mayor.")

st.caption(f"El nivel mide qué parte de la capacidad de un ómnibus ({CAPACIDAD} pasajeros) sube en esta parada: "
           f"baja menos de {UMBRAL_MEDIA:.0%}, media de {UMBRAL_MEDIA:.0%} a {UMBRAL_ALTA:.0%}, alta desde {UMBRAL_ALTA:.0%}. "
           "Mide cuánta gente sube aquí por cada ómnibus programado; no incluye a quienes ya vienen a bordo.")
