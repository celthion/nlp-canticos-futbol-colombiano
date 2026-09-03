"""Integra las capturas, elimina duplicados reales y marca similitudes dudosas.

La transformación usada para comparar nunca sustituye ``letra_original``.
Solo se deduplican registros del mismo club con secuencia canónica completa
idéntica. Las semejanzas altas se conservan para revisión humana.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datos"

USEFUL_CONTEXT = {
    ("CLU006", "Miren Miren Que Locura"): {
        "contexto_cantico": "FanChants presenta la letra como un canto a Juan Pablo Ángel; Atlético Nacional confirma que marcó el gol con el que el club obtuvo el título de 1994.",
        "referente_contextual": "Juan Pablo Ángel",
        "fuente_contexto": "https://atlnacional.com.co/1994-el-titulo-de-rene/",
        "estado_contexto": "verificado con fuente externa",
    },
    ("CLU006", "¡Macnelly Torres!"): {
        "contexto_cantico": "FanChants presenta la letra como un canto a Macnelly Torres; Atlético Nacional lo identifica como creador del mediocampo campeón de la Copa Libertadores 2016.",
        "referente_contextual": "Macnelly Torres",
        "fuente_contexto": "https://atlnacional.com.co/magia-y-creacion/",
        "estado_contexto": "verificado con fuente externa",
    },
    ("CLU014", "Ole Omar"): {
        "contexto_cantico": "FanChants presenta la letra como un homenaje a Omar; Independiente Santa Fe identifica a Ómar Sebastián Pérez como jugador, capitán y uno de sus mayores ídolos.",
        "referente_contextual": "Ómar Sebastián Pérez",
        "fuente_contexto": "https://independientesantafe.com/2019/03/09/comunicado-oficial-situacion-medica-omar-sebastian-perez/",
        "estado_contexto": "verificado con fuente externa",
    },
    ("CLU009", "¡Uruguayo!"): {
        "contexto_cantico": "La captura de FanChants aportada al proyecto describe el canto como apoyo al uruguayo Ernesto Hernández; El Tiempo lo identifica como arquero uruguayo vinculado al Deportivo Cali.",
        "referente_contextual": "Ernesto Hernández",
        "fuente_contexto": "https://www.eltiempo.com/archivo/documento/cms-15109815",
        "estado_contexto": "verificado con fuente externa",
    },
    ("CLU006", "¡Galeano!"): {
        "contexto_cantico": "FanChants solo menciona el apellido Galeano. No se asigna un nombre completo porque la página no permite desambiguarlo con seguridad.",
        "referente_contextual": "Galeano (sin desambiguar)",
        "fuente_contexto": "",
        "estado_contexto": "referente no desambiguado",
    },
}

INPUTS = [
    DATA / "fanchants_atletico_nacional.json",
    DATA / "fanchants_millonarios_santafe.json",
    DATA / "fanchants_dim_cali.json",
    DATA / "fanchants_once_tolima.json",
    DATA / "fanchants_junior.json",
    DATA / "fanchants_america_completo.json",
    DATA / "fanchants_paginas_pendientes.json",
    DATA / "canticos_crudos_fuentes_adicionales.json",
]

FIELDS = [
    "cantico_id",
    "club_id",
    "equipo_mencionado_fuente",
    "titulo_referencia",
    "letra_original",
    "contexto_cantico",
    "referente_contextual",
    "fuente_contexto",
    "estado_contexto",
    "fuente",
    "url",
    "fecha_consulta",
    "fecha_publicacion",
    "metodo_adquisicion",
    "numero_palabras",
    "estado_verificacion",
    "posible_similar_a",
    "revision_manual",
    "observacion_revision",
]


def canonical(text: str) -> str:
    """Copia temporal para comparación; no se guarda en el corpus."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def word_count(text: str) -> int:
    # Mantiene números y grafías identitarias como unidades del conteo.
    return len(re.findall(r"\w+(?:['’*]+\w+)*", text, flags=re.UNICODE))


def similarity(a: str, b: str) -> tuple[float, float, float]:
    ta, tb = a.split(), b.split()
    seq = SequenceMatcher(None, ta, tb, autojunk=False).ratio()
    sa, sb = set(ta), set(tb)
    jaccard = len(sa & sb) / len(sa | sb) if sa or sb else 0.0
    length_ratio = min(len(ta), len(tb)) / max(len(ta), len(tb)) if ta and tb else 0.0
    return seq, jaccard, length_ratio


def load_rows() -> list[dict[str, str]]:
    context_payload = json.loads((DATA / "fanchants_contextos.json").read_text(encoding="utf-8"))
    contexts = {item["url"]: item for item in context_payload.get("registros", [])}
    rows: list[dict[str, str]] = []
    for path in INPUTS:
        if not path.exists():
            raise FileNotFoundError(f"Falta el insumo esperado: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for original in payload.get("registros", []):
            row = original.copy()
            # Las páginas recuperadas de la paginación usan las etiquetas del navegador.
            row["titulo_referencia"] = row.get("titulo_referencia") or row.get("title", "")
            row["equipo_mencionado_fuente"] = row.get("equipo_mencionado_fuente") or row.get("equipo", "")
            if row.get("fuente") == "FanChants":
                context = contexts.get(row.get("url", ""), {})
                for field in [
                    "contexto_fuente", "historia_fuente", "referente_contextual",
                    "tipo_referente", "fuente_contexto", "observacion_contexto",
                ]:
                    row[field] = row.get(field) or context.get(field, "")
            for field in [
                "contexto_fuente", "historia_fuente", "referente_contextual",
                "tipo_referente", "fuente_contexto", "observacion_contexto",
            ]:
                row.setdefault(field, "")
            # Solo se conserva contexto que desambigua un referente o aporta un hecho
            # útil y comprobable. Las descripciones genéricas de apoyo, emoción o
            # pertenencia repiten la letra y se omiten del corpus analítico.
            useful = USEFUL_CONTEXT.get((row.get("club_id", ""), row.get("titulo_referencia", "")), {})
            row["contexto_cantico"] = useful.get("contexto_cantico", "")
            row["referente_contextual"] = useful.get("referente_contextual", "")
            row["fuente_contexto"] = useful.get("fuente_contexto", "")
            row["estado_contexto"] = useful.get("estado_contexto", "")
            rows.append(row)
    return rows


def integrate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    kept: list[dict[str, str]] = []
    exact_index: dict[tuple[str, str], int] = {}
    duplicate_log: list[dict[str, str]] = []

    for row in rows:
        lyric = str(row.get("letra_original", "")).strip()
        if not lyric:
            continue
        key = (row["club_id"], canonical(lyric))
        if key in exact_index:
            survivor = kept[exact_index[key]]
            # Preferimos la captura que conserva más estructura visible.
            replace = ("\n" in lyric and "\n" not in survivor["letra_original"]) or len(lyric) > len(survivor["letra_original"]) * 1.05
            removed, retained = (survivor, row) if replace else (row, survivor)
            if replace:
                kept[exact_index[key]] = row.copy()
                survivor = kept[exact_index[key]]
            note = f"Duplicado exacto también localizado en {removed.get('fuente', '')}: {removed.get('url', '')}"
            survivor["_duplicate_note"] = "; ".join(filter(None, [survivor.get("_duplicate_note", ""), note]))
            duplicate_log.append(
                {
                    "club_id": row["club_id"],
                    "titulo_conservado": retained.get("titulo_referencia", ""),
                    "fuente_conservada": retained.get("fuente", ""),
                    "url_conservada": retained.get("url", ""),
                    "titulo_descartado": removed.get("titulo_referencia", ""),
                    "fuente_descartada": removed.get("fuente", ""),
                    "url_descartada": removed.get("url", ""),
                    "regla": "secuencia canónica completa idéntica dentro del mismo club",
                }
            )
            continue
        exact_index[key] = len(kept)
        kept.append(row.copy())

    kept.sort(key=lambda r: (r["club_id"], r.get("fuente", ""), r.get("titulo_referencia", "").casefold()))
    for number, row in enumerate(kept, 1):
        row["cantico_id"] = f"CAN{number:04d}"
        row["numero_palabras"] = word_count(row["letra_original"])
        row["estado_verificacion"] = "aceptado"
        row["posible_similar_a"] = ""
        row["revision_manual"] = "No"
        row["observacion_revision"] = row.pop("_duplicate_note", "")

    # Casos cuya propia fuente presenta señales contradictorias de asociación.
    association_flags = {
        ("CLU006", "Que Lo Vengan a Ver"): "La descripción histórica de FanChants menciona América de Cali aunque la página está alojada bajo Atlético Nacional.",
        ("CLU006", "Oh No Les Da Verguenza"): "La descripción histórica de FanChants menciona Independiente Medellín aunque la página está alojada bajo Atlético Nacional.",
        ("CLU003", "Esta Hinchada No Te Deja de Alentar"): "La URL y la descripción histórica de FanChants mencionan Deportivo Cali; revisar asociación con América de Cali.",
    }
    for row in kept:
        note = association_flags.get((row["club_id"], row["titulo_referencia"]))
        if note:
            row["estado_verificacion"] = "requiere revisión: asociación con club"
            row["revision_manual"] = "Sí"
            row["observacion_revision"] = "; ".join(filter(None, [row["observacion_revision"], note]))

        if row.get("revision_fuente") == "Sí":
            row["estado_verificacion"] = "requiere revisión: segmentación de fuente"
            row["revision_manual"] = "Sí"
            row["observacion_revision"] = "; ".join(filter(None, [row["observacion_revision"], row.get("motivo_revision_fuente", "")]))

    # Se comparan letras solo dentro del mismo club. Nunca se eliminan aquí.
    by_club: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(kept):
        by_club[row["club_id"]].append(i)

    similar: dict[int, list[tuple[int, float, float, float]]] = defaultdict(list)
    canon = [canonical(row["letra_original"]) for row in kept]
    for indices in by_club.values():
        for pos, i in enumerate(indices):
            for j in indices[pos + 1 :]:
                seq, jac, lr = similarity(canon[i], canon[j])
                # Umbral conservador: evita marcar simples coros compartidos.
                if (seq >= 0.88 and lr >= 0.72) or (seq >= 0.82 and jac >= 0.80 and lr >= 0.82):
                    similar[i].append((j, seq, jac, lr))
                    similar[j].append((i, seq, jac, lr))

    for i, matches in similar.items():
        ids = [kept[j]["cantico_id"] for j, *_ in matches]
        metrics = [f"{kept[j]['cantico_id']} (secuencia={seq:.3f}, vocabulario={jac:.3f}, longitud={lr:.3f})" for j, seq, jac, lr in matches]
        kept[i]["posible_similar_a"] = " | ".join(ids)
        kept[i]["revision_manual"] = "Sí"
        if kept[i]["estado_verificacion"] == "aceptado":
            kept[i]["estado_verificacion"] = "requiere revisión: similitud"
        kept[i]["observacion_revision"] = "; ".join(
            filter(None, [kept[i]["observacion_revision"], "Similitud alta conservada: " + " | ".join(metrics)])
        )

    return kept, duplicate_log


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    raw = load_rows()
    corpus, duplicates = integrate(raw)
    write_csv(DATA / "canticos.csv", corpus, FIELDS)
    duplicate_fields = [
        "club_id", "titulo_conservado", "fuente_conservada", "url_conservada",
        "titulo_descartado", "fuente_descartada", "url_descartada", "regla",
    ]
    write_csv(DATA / "duplicados_exactos.csv", duplicates, duplicate_fields)

    declared_fanchants = {
        "CLU003": 3,
        "CLU006": 42,
        "CLU009": 18,
        "CLU010": 17,
        "CLU012": 17,
        "CLU014": 31,
        "CLU017": 1,
        "CLU019": 31,
        "CLU020": 17,
    }
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in corpus:
        counts[(row["club_id"], row["fuente"])] += 1
    with (DATA / "clubes.csv").open(encoding="utf-8-sig", newline="") as fh:
        clubs = list(csv.DictReader(fh))
    coverage = []
    for club in clubs:
        club_id = club["club_id"]
        declared = declared_fanchants.get(club_id, 0)
        fan = counts[(club_id, "FanChants")]
        barra = counts[(club_id, "Barrabrava.net")]
        if declared and fan >= declared:
            status = "cobertura FanChants completa en la fecha de consulta"
        elif fan:
            status = "cobertura FanChants parcial por fallo de paginación"
        elif barra:
            status = "registros de otra fuente; FanChants no localizado"
        else:
            status = "sin letra localizada en la primera pasada"
        coverage.append(
            {
                "club_id": club_id,
                "nombre_corto": club["nombre_corto"],
                "fanchants_total_declarado": declared,
                "fanchants_recuperados": fan,
                "barrabrava_recuperados": barra,
                "registros_finales": sum(1 for row in corpus if row["club_id"] == club_id),
                "estado_primera_pasada": status,
                "interpretacion": "Cobertura digital localizada; cero no equivale a ausencia de repertorio.",
            }
        )
    write_csv(
        DATA / "control_cobertura.csv",
        coverage,
        [
            "club_id", "nombre_corto", "fanchants_total_declarado", "fanchants_recuperados",
            "barrabrava_recuperados", "registros_finales", "estado_primera_pasada", "interpretacion",
        ],
    )
    summary = {
        "capturas_crudas": len(raw),
        "duplicados_exactos_eliminados": len(duplicates),
        "registros_finales": len(corpus),
        "registros_revision_manual": sum(r["revision_manual"] == "Sí" for r in corpus),
        "clubes_con_canticos": len({r["club_id"] for r in corpus}),
    }
    (DATA / "resumen_calidad.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
