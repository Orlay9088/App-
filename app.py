#!/usr/bin/env python3
"""
SocialPulse - Backend API para gestión de contenido en redes sociales
Ejecutar: python app.py
"""

import sqlite3
import json
import os
import csv
import io
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import re
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "socialpulse.db")
IG_GRAPH_BASE = "https://graph.facebook.com/v22.0"

# ─── Base de datos ────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            dia_semana TEXT NOT NULL,
            tipo_contenido TEXT NOT NULL,
            objetivo TEXT NOT NULL,
            tema TEXT NOT NULL,
            cta TEXT NOT NULL,
            descripcion TEXT,
            interacciones_esperadas INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'programado',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metricas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL UNIQUE,
            likes INTEGER DEFAULT 0,
            comentarios INTEGER DEFAULT 0,
            compartidos INTEGER DEFAULT 0,
            guardados INTEGER DEFAULT 0,
            respuestas_dm INTEGER DEFAULT 0,
            nuevos_seguidores INTEGER DEFAULT 0,
            fecha_medicion TEXT,
            notas TEXT,
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS smartlinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            url TEXT NOT NULL,
            clicks INTEGER DEFAULT 0,
            orden INTEGER DEFAULT 0,
            activo INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Lightweight migration for existing databases.
    c.execute("PRAGMA table_info(posts)")
    post_columns = {row[1] for row in c.fetchall()}
    if "instagram_media_id" not in post_columns:
        c.execute("ALTER TABLE posts ADD COLUMN instagram_media_id TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_instagram_media_id ON posts(instagram_media_id)")
    if "instagram_permalink" not in post_columns:
        c.execute("ALTER TABLE posts ADD COLUMN instagram_permalink TEXT")
    if "image_url" not in post_columns:
        c.execute("ALTER TABLE posts ADD COLUMN image_url TEXT")

    conn.commit()
    conn.close()

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enforce SQLite FK constraints so metricas cannot reference missing posts.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def parse_int(value, field_name, default=0, minimum=0):
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' debe ser un número entero")
    if parsed < minimum:
        raise ValueError(f"'{field_name}' debe ser mayor o igual a {minimum}")
    return parsed

def parse_iso_date(value, field_name):
    if not value:
        raise ValueError(f"'{field_name}' es requerido")
    try:
        # Strict validation
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' debe tener formato YYYY-MM-DD")
    return value

def validate_url(value, field_name, required=False):
    if not value:
        if required:
            raise ValueError(f"'{field_name}' es requerido")
        return ""
    # Simple regex for URL validation
    regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' # domain...
        r'localhost|' # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    if not re.match(regex, value):
        raise ValueError(f"'{field_name}' debe ser una URL válida")
    return value

def get_env(name, required=False):
    value = os.getenv(name, "").strip()
    if required and not value:
        raise ValueError(f"Falta variable de entorno: {name}")
    return value

def get_ig_config():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT key, value FROM config WHERE key IN ('INSTAGRAM_BUSINESS_ACCOUNT_ID', 'INSTAGRAM_ACCESS_TOKEN')")
        rows = c.fetchall()
    
    config_db = {row['key']: row['value'] for row in rows}
    
    account_id = config_db.get("INSTAGRAM_BUSINESS_ACCOUNT_ID") or get_env("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    token = config_db.get("INSTAGRAM_ACCESS_TOKEN") or get_env("INSTAGRAM_ACCESS_TOKEN")
    if not account_id or not token:
        raise ValueError(
            "Configura INSTAGRAM_BUSINESS_ACCOUNT_ID e INSTAGRAM_ACCESS_TOKEN "
            "en la interfaz de configuración o variables de entorno."
        )
    return {"account_id": account_id, "token": token}

def graph_get(path, params):
    query = urlencode(params)
    url = f"{IG_GRAPH_BASE}/{path}?{query}"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw)
            msg = payload.get("error", {}).get("message") or raw
        except json.JSONDecodeError:
            msg = raw or str(e)
        raise ValueError(f"Instagram API error: {msg}")
    except URLError:
        raise ValueError("No se pudo conectar con Instagram Graph API")

def graph_post(path, params):
    data = urlencode(params).encode("utf-8")
    url = f"{IG_GRAPH_BASE}/{path}"
    req = Request(url, data=data, method="POST")
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw)
            msg = payload.get("error", {}).get("message") or raw
        except json.JSONDecodeError:
            msg = raw or str(e)
        raise ValueError(f"Instagram API error: {msg}")
    except URLError:
        raise ValueError("No se pudo conectar con Instagram Graph API")

def infer_tipo_from_caption(caption):
    text = (caption or "").lower()
    if "?" in text or "encuesta" in text:
        return "pregunta"
    if "oferta" in text or "promo" in text or "descuento" in text:
        return "promocional"
    if "historia" in text or "story" in text:
        return "storytelling"
    if "tip" in text or "cómo" in text or "guía" in text:
        return "educativo"
    return "otro"

def sync_instagram_posts_and_metrics(limit=25):
    cfg = get_ig_config()
    token = cfg["token"]
    account_id = cfg["account_id"]

    media_response = graph_get(
        f"{account_id}/media",
        {
            "fields": "id,caption,media_type,timestamp,permalink",
            "limit": str(limit),
            "access_token": token,
        },
    )
    media_items = media_response.get("data", [])
    
    imported = 0
    updated = 0

    with get_conn() as conn:
        c = conn.cursor()
        for media in media_items:
            try:
                media_id = media.get("id")
                if not media_id:
                    continue
                timestamp = str(media.get("timestamp", ""))
                fecha = timestamp[:10] if timestamp else str(date.today())
                try:
                    d = datetime.strptime(fecha, "%Y-%m-%d")
                    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                    dia = dias[d.weekday()]
                except ValueError:
                    dia = "Desconocido"
                    fecha = str(date.today())

                caption = str(media.get("caption") or "").strip()
                tema = caption[:200] if caption else f"Post Instagram {media_id}"
                permalink = media.get("permalink") or ""
                tipo = infer_tipo_from_caption(caption)

                c.execute("SELECT id FROM posts WHERE instagram_media_id=?", (media_id,))
                row = c.fetchone()
                if row:
                    post_id = row["id"]
                else:
                    c.execute(
                        """
                        INSERT INTO posts (
                            fecha, dia_semana, tipo_contenido, objetivo, tema, cta, descripcion,
                            interacciones_esperadas, estado, instagram_media_id, instagram_permalink
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            fecha,
                            dia,
                            tipo,
                            tema,
                            "Ver post en Instagram",
                            str(caption)[:2000],
                            0,
                            "programado",
                            media_id,
                            permalink,
                        ),
                    )
                    post_id = c.lastrowid
                    imported += 1

                # 🛡️ Blindaje: Si falla la obtención de métricas de un post, continuamos con el siguiente.
                try:
                    insights = graph_get(
                        media_id,
                        {
                            "fields": "like_count,comments_count",
                            "access_token": token,
                        },
                    )
                    likes = parse_int(insights.get("like_count", 0), "like_count")
                    comentarios = parse_int(insights.get("comments_count", 0), "comments_count")
                    
                    guardados = 0
                    compartidos = 0
                    try:
                        ins = graph_get(
                            f"{media_id}/insights",
                            {
                                "metric": "saved,shares",
                                "access_token": token
                            }
                        )
                        data = ins.get("data", [])
                        for m in data:
                            if m.get("name") == "saved":
                                guardados = sum(v.get("value", 0) for v in m.get("values", []))
                            elif m.get("name") == "shares":
                                compartidos = sum(v.get("value", 0) for v in m.get("values", []))
                    except (ValueError, Exception):
                        pass # Metric not supported or transient error for this object
                    
                    c.execute(
                        """
                        INSERT INTO metricas (post_id, likes, comentarios, compartidos, guardados,
                                              respuestas_dm, nuevos_seguidores, fecha_medicion, notas)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(post_id) DO UPDATE SET
                            likes=excluded.likes,
                            comentarios=excluded.comentarios,
                            compartidos=excluded.compartidos,
                            guardados=excluded.guardados,
                            fecha_medicion=excluded.fecha_medicion,
                            notas=excluded.notas
                        """,
                        (
                            post_id,
                            likes,
                            comentarios,
                            compartidos,
                            guardados,
                            0,
                            0,
                            str(date.today()),
                            "Sincronizado desde Instagram API",
                        ),
                    )
                    c.execute("UPDATE posts SET estado='medido', instagram_permalink=? WHERE id=?", (permalink, post_id))
                    updated += 1
                except Exception as e:
                    print(f"⚠️ Error sincronizando métricas para media {media_id}: {str(e)}")
                    continue
            except Exception as e:
                print(f"⚠️ Error procesando item de media: {str(e)}")
                continue

        conn.commit()
    return {"ok": True, "importados": imported, "metricas_actualizadas": updated, "total_recibidos": len(media_items)}

def get_instagram_status():
    try:
        cfg = get_ig_config()
        configured = True
        account_id = cfg["account_id"]
    except ValueError:
        configured = False
        account_id = None
    return {
        "configured": configured,
        "account_id": str(account_id)[-6:] if account_id else None,
    }

def get_post_comments(post_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT instagram_media_id FROM posts WHERE id=?", (post_id,))
        row = c.fetchone()
    if not row or not row["instagram_media_id"]:
        raise LookupError("Post no encontrado o no está sincronizado con IG")
    
    cfg = get_ig_config()
    token = cfg["token"]
    media_id = row["instagram_media_id"]
    
    res = graph_get(
        f"{media_id}/comments",
        {
            "fields": "id,text,timestamp,username,replies{id,text,timestamp,username}",
            "access_token": token
        }
    )
    return res.get("data", [])

def reply_to_comment(comment_id, message):
    if not message or not message.strip():
        raise ValueError("El mensaje no puede estar vacío")
    
    cfg = get_ig_config()
    res = graph_post(
        f"{comment_id}/replies",
        {
            "message": message,
            "access_token": cfg["token"]
        }
    )
    return {"ok": True, "id": res.get("id")}

def publish_post(post_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM posts WHERE id=?", (post_id,))
        row = c.fetchone()
        
        if not row:
            raise LookupError("Post no encontrado")
            
        if not row["image_url"]:
            raise ValueError("El post debe tener una URL de imagen válida para ser publicado en Instagram")
            
        cfg = get_ig_config()
        account_id = cfg["account_id"]
        token = cfg["token"]
        
        caption_text = f"{row['tema']}\n\n{row['descripcion']}" if row['descripcion'] else row['tema']
        
        # 1. Create Media Container
        container_res = graph_post(
            f"{account_id}/media",
            {
                "image_url": row["image_url"],
                "caption": caption_text,
                "access_token": token
            }
        )
        creation_id = container_res.get("id")
        if not creation_id:
            raise ValueError("Error al crear el contenedor de medios en Instagram")
            
        # 2. Publish Media
        publish_res = graph_post(
            f"{account_id}/media_publish",
            {
                "creation_id": creation_id,
                "access_token": token
            }
        )
        media_id = publish_res.get("id")
        if not media_id:
            raise ValueError("Error al publicar el post en Instagram")
            
        # Attempt to fetch permalink from graph
        permalink = ""
        try:
            media_data = graph_get(media_id, {"fields": "permalink", "access_token": token})
            permalink = media_data.get("permalink", "")
        except Exception:
            pass
            
        c.execute("""
            UPDATE posts 
            SET estado='publicado', instagram_media_id=?, instagram_permalink=? 
            WHERE id=?
        """, (media_id, permalink, post_id))
        conn.commit()
    
    return {"ok": True, "media_id": media_id, "permalink": permalink}

import random

def generar_caption_ia(tema, objetivo):
    tema_limpio = tema.strip() if tema else "nuestro último contenido"
    if objetivo in ["vender", "atraer_clientes"]:
        vars_cap = [
            f"🔥 ¡Es el momento de transformar tu enfoque! Descubre todo sobre {tema_limpio} y lleva tus resultados al siguiente nivel. 🚀\n\n¿Estás listo para dar el paso? 👇",
            f"¿Llevas tiempo pensando en {tema_limpio}? 🤔 Deja de darle vueltas y descubre nuestra estrategia completa. ¡Resultados garantizados! ✨\n\nHaz clic en el enlace de nuestra bio para empezar.",
            f"⚡ Oferta especial ⚡ Porque sabemos que {tema_limpio} es clave para tu éxito. No dejes pasar esta oportunidad única. ⏳"
        ]
    elif objetivo in ["educar", "visibilidad"]:
        vars_cap = [
            f"📚 3 claves fundamentales sobre {tema_limpio} que nadie te ha contado. ¡Desliza para descubrirlas! 👉\n\n1️⃣ La paciencia paga.\n2️⃣ La estrategia manda.\n3️⃣ Tú tienes el control.\n\n¿Cuál es tu opinión al respecto?",
            f"💡 Hablemos de algo importante: {tema_limpio}. Muchas veces lo pasamos por alto, pero dominar este concepto cambiará tu perspectiva por completo.\n\nGuarda este post para leerlo más tarde. 🔖",
            f"El mito más grande sobre {tema_limpio} al descubierto. 🤯 Mitos vs Realidades en nuestro nuevo análisis. ¿Tú de qué lado estás?"
        ]
    else:
        vars_cap = [
            f"✨ Hoy queremos compartir algo muy especial relacionado con {tema_limpio}. Cada pequeño paso cuenta en este viaje.\n\n¡Déjanos un comentario si estás de acuerdo! 👇",
            f"¿Qué significa realmente {tema_limpio} para ti? Para nosotros es inspiración constante. 🌟\n\nTe leemos en los comentarios. 💬",
            f"Haciendo que {tema_limpio} sea parte de nuestra rutina. 🌿 Un día a la vez. ¡Menciona a alguien que necesite ver esto!"
        ]
    
    random.shuffle(vars_cap)
    tonos = ["Persuasivo", "Educativo", "Cercano", "Directo"]
    ops = []
    for i, v in enumerate(vars_cap[:3]):
        # Ensure hashtag doesn't have spaces and is alphanumeric
        hashtag = "".join(e for e in str(tema_limpio).split()[0] if e.isalnum())
        ops.append({
            "texto": v + "\n\n#socialmedia #estrategia #" + hashtag,
            "tono": tonos[i % len(tonos)]
        })
    return {"ok": True, "opciones": ops}

# ─── Lógica de negocio ────────────────────────────────────────────────────────

def crear_post(data):
    fecha = parse_iso_date(data.get("fecha", ""), "fecha")
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d")
        dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
        dia = dias[d.weekday()]
    except (TypeError, ValueError):
        dia = "Desconocido"

    required_fields = ["tipo_contenido", "objetivo", "tema", "cta"]
    for field in required_fields:
        if not str(data.get(field, "")).strip():
            raise ValueError(f"'{field}' es requerido")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO posts (fecha, dia_semana, tipo_contenido, objetivo, tema, cta,
                               descripcion, interacciones_esperadas, image_url)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            fecha, dia,
            data.get("tipo_contenido",""),
            data.get("objetivo",""),
            data.get("tema",""),
            data.get("cta",""),
            data.get("descripcion",""),
            parse_int(data.get("interacciones_esperadas", 0), "interacciones_esperadas"),
            validate_url(data.get("image_url", ""), "image_url")
        ))
        conn.commit()
        post_id = c.lastrowid
    return {"ok": True, "id": post_id, "dia_semana": dia}

def editar_post(post_id, data):
    fecha = parse_iso_date(data.get("fecha", ""), "fecha")
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d")
        dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
        dia = dias[d.weekday()]
    except (TypeError, ValueError):
        dia = "Desconocido"

    required_fields = ["tipo_contenido", "objetivo", "tema", "cta"]
    for field in required_fields:
        if not str(data.get(field, "")).strip():
            raise ValueError(f"'{field}' es requerido")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM posts WHERE id=?", (post_id,))
        if not c.fetchone():
            raise LookupError("Post no encontrado")

        c.execute("""
            UPDATE posts
            SET fecha=?, dia_semana=?, tipo_contenido=?, objetivo=?, tema=?, cta=?,
                descripcion=?, interacciones_esperadas=?, image_url=?
            WHERE id=?
        """, (
            fecha, dia,
            data.get("tipo_contenido",""),
            data.get("objetivo",""),
            data.get("tema",""),
            data.get("cta",""),
            data.get("descripcion",""),
            parse_int(data.get("interacciones_esperadas", 0), "interacciones_esperadas"),
            validate_url(data.get("image_url", ""), "image_url"),
            post_id
        ))
        conn.commit()
    return {"ok": True, "id": post_id, "dia_semana": dia}

def registrar_metricas(post_id, data):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM posts WHERE id=?", (post_id,))
        if not c.fetchone():
            raise LookupError("Post no encontrado")

        fecha_medicion = data.get("fecha_medicion", str(date.today()))
        if fecha_medicion:
            parse_iso_date(fecha_medicion, "fecha_medicion")

        c.execute("""
            INSERT INTO metricas (post_id, likes, comentarios, compartidos, guardados,
                                   respuestas_dm, nuevos_seguidores, fecha_medicion, notas)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
                likes=excluded.likes,
                comentarios=excluded.comentarios,
                compartidos=excluded.compartidos,
                guardados=excluded.guardados,
                respuestas_dm=excluded.respuestas_dm,
                nuevos_seguidores=excluded.nuevos_seguidores,
                fecha_medicion=excluded.fecha_medicion,
                notas=excluded.notas
        """, (
            post_id,
            parse_int(data.get("likes", 0), "likes"),
            parse_int(data.get("comentarios", 0), "comentarios"),
            parse_int(data.get("compartidos", 0), "compartidos"),
            parse_int(data.get("guardados", 0), "guardados"),
            parse_int(data.get("respuestas_dm", 0), "respuestas_dm"),
            parse_int(data.get("nuevos_seguidores", 0), "nuevos_seguidores"),
            fecha_medicion,
            data.get("notas", "")
        ))
        c.execute("UPDATE posts SET estado='medido' WHERE id=?", (post_id,))
        conn.commit()
    return {"ok": True}

def get_csv_report():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT p.id, p.fecha, p.dia_semana, p.tipo_contenido, p.objetivo, p.tema, p.estado,
                   m.likes, m.comentarios, m.compartidos, m.guardados, m.respuestas_dm,
                   m.fecha_medicion,
                   (COALESCE(m.likes,0)+COALESCE(m.comentarios,0)*2+COALESCE(m.compartidos,0)*3
                    +COALESCE(m.guardados,0)*4+COALESCE(m.respuestas_dm,0)*5) as interaccion_total
            FROM posts p LEFT JOIN metricas m ON p.id = m.post_id
            ORDER BY p.fecha DESC
        """)
        rows = c.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Fecha", "Día", "Tipo", "Objetivo", "Tema", "Estado", 
        "Likes", "Comentarios", "Compartidos", "Guardados", "Resp_DM", 
        "Interaccion_Total", "Fecha_Medicion"
    ])
    for row in rows:
        writer.writerow([
            row["id"], row["fecha"], row["dia_semana"], row["tipo_contenido"],
            row["objetivo"], row["tema"].replace('\n', ' '), row["estado"],
            row["likes"] if row["likes"] is not None else 0,
            row["comentarios"] if row["comentarios"] is not None else 0,
            row["compartidos"] if row["compartidos"] is not None else 0,
            row["guardados"] if row["guardados"] is not None else 0,
            row["respuestas_dm"] if row["respuestas_dm"] is not None else 0,
            row["interaccion_total"],
            row["fecha_medicion"] or ""
        ])
    return output.getvalue()

def get_posts():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT p.*, m.likes, m.comentarios, m.compartidos, m.guardados,
                   m.respuestas_dm, m.nuevos_seguidores, m.notas, m.fecha_medicion,
                   (COALESCE(m.likes,0)+COALESCE(m.comentarios,0)*2+COALESCE(m.compartidos,0)*3
                    +COALESCE(m.guardados,0)*4+COALESCE(m.respuestas_dm,0)*5) as interaccion_total
            FROM posts p LEFT JOIN metricas m ON p.id = m.post_id
            ORDER BY p.fecha DESC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows

def get_parrilla():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, fecha, dia_semana, tipo_contenido, tema, descripcion, estado, instagram_permalink, image_url
            FROM posts
            ORDER BY fecha ASC
        """)
        rows = [dict(r) for r in c.fetchall()]
    return rows

def get_config_keys():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT key, value FROM config")
        rows = {r['key']: r['value'] for r in c.fetchall()}
    # Mask the token for safety when reading
    if "INSTAGRAM_ACCESS_TOKEN" in rows and rows["INSTAGRAM_ACCESS_TOKEN"]:
        rows["INSTAGRAM_ACCESS_TOKEN"] = rows["INSTAGRAM_ACCESS_TOKEN"][:4] + "***"
    return rows

def set_config_keys(data):
    # We only allow updating these keys
    allowed_keys = ["INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN", "EXTERNAL_GRID_URL"]
    
    with get_conn() as conn:
        c = conn.cursor()
        for key, val in data.items():
            if key in allowed_keys:
                # If value contains "***", do not overwrite it.
                if "***" in val:
                    continue
                c.execute("""
                    INSERT INTO config (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """, (key, val))
        conn.commit()
    return {"ok": True}

def get_analisis():
    with get_conn() as conn:
        c = conn.cursor()

        # Promedio por tipo de contenido
        c.execute("""
            SELECT p.tipo_contenido,
                   COUNT(*) as total_posts,
                   AVG(COALESCE(m.likes,0)) as avg_likes,
                   AVG(COALESCE(m.comentarios,0)) as avg_comentarios,
                   AVG(COALESCE(m.compartidos,0)) as avg_compartidos,
                   AVG(COALESCE(m.guardados,0)) as avg_guardados,
                   AVG(COALESCE(m.likes,0)+COALESCE(m.comentarios,0)*2+COALESCE(m.compartidos,0)*3
                       +COALESCE(m.guardados,0)*4+COALESCE(m.respuestas_dm,0)*5) as avg_interaccion
            FROM posts p LEFT JOIN metricas m ON p.id = m.post_id
            GROUP BY p.tipo_contenido
            ORDER BY avg_interaccion DESC
        """)
        por_tipo = [dict(r) for r in c.fetchall()]

        # Promedio por día
        c.execute("""
            SELECT p.dia_semana,
                   COUNT(*) as total_posts,
                   AVG(COALESCE(m.likes,0)+COALESCE(m.comentarios,0)*2+COALESCE(m.compartidos,0)*3
                       +COALESCE(m.guardados,0)*4+COALESCE(m.respuestas_dm,0)*5) as avg_interaccion
            FROM posts p LEFT JOIN metricas m ON p.id = m.post_id
            WHERE m.id IS NOT NULL
            GROUP BY p.dia_semana
            ORDER BY avg_interaccion DESC
        """)
        por_dia = [dict(r) for r in c.fetchall()]

        # Totales generales
        c.execute("""
            SELECT COUNT(*) as total_posts,
                   COUNT(m.id) as posts_medidos,
                   SUM(COALESCE(m.likes,0)) as total_likes,
                   SUM(COALESCE(m.comentarios,0)) as total_comentarios,
                   SUM(COALESCE(m.compartidos,0)) as total_compartidos,
                   SUM(COALESCE(m.guardados,0)) as total_guardados
            FROM posts p LEFT JOIN metricas m ON p.id = m.post_id
        """)
        totales = dict(c.fetchone())

    # Insights automáticos
    insights = generar_insights(por_tipo, por_dia, totales)

    return {
        "por_tipo": por_tipo,
        "por_dia": por_dia,
        "totales": totales,
        "insights": insights
    }

def generar_insights(por_tipo, por_dia, totales):
    insights: list[str] = []
    if por_tipo and len(por_tipo) >= 2:
        mejor = por_tipo[0]
        peor = por_tipo[-1]
        if mejor["avg_interaccion"] and peor["avg_interaccion"] and peor["avg_interaccion"] > 0:
            ratio = round(mejor["avg_interaccion"] / peor["avg_interaccion"], 1)
            insights.append(f"📈 El contenido '{mejor['tipo_contenido']}' genera {ratio}x más interacción que '{peor['tipo_contenido']}'")

    if por_dia and len(por_dia) >= 1:
        insights.append(f"📅 Tu mejor día de publicación es {por_dia[0]['dia_semana']} con un promedio de {round(por_dia[0]['avg_interaccion'] or 0)} pts de interacción")

    if totales["total_posts"] > 0 and totales["posts_medidos"] > 0:
        tasa = round((totales["posts_medidos"] / totales["total_posts"]) * 100)
        insights.append(f"📊 Has medido el {tasa}% de tus posts ({totales['posts_medidos']}/{totales['total_posts']})")

    if totales["total_guardados"] and totales["total_likes"] and totales["total_likes"] > 0:
        ratio_g = round((totales["total_guardados"] / totales["total_likes"]) * 100, 1)
        if ratio_g > 20:
            insights.append(f"⭐ Tu ratio de guardados/likes es {ratio_g}% — señal de contenido de alto valor")

    return insights

def eliminar_post(post_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM posts WHERE id=?", (post_id,))
        if not c.fetchone():
            raise LookupError("Post no encontrado")
        c.execute("DELETE FROM metricas WHERE post_id=?", (post_id,))
        c.execute("DELETE FROM posts WHERE id=?", (post_id,))
        conn.commit()
    return {"ok": True}

# ─── SmartLinks (Link-in-bio) ─────────────────────────────────────────────────

def get_smartlinks():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM smartlinks ORDER BY orden ASC, created_at DESC")
        rows = [dict(r) for r in c.fetchall()]
    return rows

def create_smartlink(data):
    titulo = str(data.get("titulo", "")).strip()
    url_link = validate_url(data.get("url", ""), "url", required=True)
    if not titulo:
        raise ValueError("Título es requerido")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO smartlinks (titulo, url) VALUES (?, ?)", (titulo, url_link))
        conn.commit()
    return {"ok": True}

def edit_smartlink(link_id, data):
    titulo = str(data.get("titulo", "")).strip()
    url_link = validate_url(data.get("url", ""), "url", required=True)
    activo = int(data.get("activo", 1))
    if not titulo:
        raise ValueError("Título es requerido")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE smartlinks SET titulo=?, url=?, activo=? WHERE id=?", (titulo, url_link, activo, link_id))
        conn.commit()
    return {"ok": True}

def delete_smartlink(link_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM smartlinks WHERE id=?", (link_id,))
        conn.commit()
    return {"ok": True}

def track_smartlink_click(link_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE smartlinks SET clicks = clicks + 1 WHERE id=?", (link_id,))
        conn.commit()
    return {"ok": True}

# ─── Servidor HTTP ────────────────────────────────────────────────────────────

def json_response(handler, data, status=200):
    try:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as e:
        print(f"Error fatal en json_response: {e}")
        # Final fallback if something crashes during response generation
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(b'{"error":"Error interno al generar respuesta"}')

def file_response(handler, filepath, content_type):
    try:
        absolute_path = os.path.join(BASE_DIR, filepath)
        with open(absolute_path, "rb") as f:
            body = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            file_response(self, "index.html", "text/html; charset=utf-8")
        elif path == "/parrilla" or path == "/parrilla.html":
            file_response(self, "parrilla.html", "text/html; charset=utf-8")
        elif path == "/bio" or path == "/bio.html":
            file_response(self, "bio.html", "text/html; charset=utf-8")
        elif path == "/api/posts":
            json_response(self, get_posts())
        elif path == "/api/parrilla":
            json_response(self, get_parrilla())
        elif path == "/api/smartlinks":
            json_response(self, get_smartlinks())
        elif path == "/api/smartlinks/public":
            links = get_smartlinks()
            # return only active public links
            json_response(self, [l for l in links if l['activo'] == 1])
        elif path == "/api/analisis":
            json_response(self, get_analisis())
        elif path == "/api/export":
            csv_data = get_csv_report()
            body = csv_data.encode("utf-8-sig")  # Excel compatible
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="socialpulse_report.csv"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/integrations/instagram/status":
            json_response(self, get_instagram_status())
        elif path == "/api/config":
            json_response(self, get_config_keys())
        elif m := re.match(r"/api/posts/(\d+)/comments$", path):
            post_id = int(m.group(1))
            try:
                json_response(self, get_post_comments(post_id))
            except Exception as e:
                json_response(self, {"error": str(e)}, 400)
        elif not path.startswith("/api/"):
            # Fallback for SPA routing: serve index.html for other non-API routes
            file_response(self, "index.html", "text/html; charset=utf-8")
        else:
            json_response(self, {"error": "Not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            json_response(self, {"error": "JSON inválido"}, 400)
            return

        path = urlparse(self.path).path

        try:
            if path == "/api/posts":
                result = crear_post(data)
                json_response(self, result, 201)
            elif path == "/api/smartlinks":
                result = create_smartlink(data)
                json_response(self, result, 201)
            elif path == "/api/config":
                result = set_config_keys(data)
                json_response(self, result)
            elif path == "/api/ai/generate":
                result = generar_caption_ia(data.get("tema", ""), data.get("objetivo", ""))
                json_response(self, result)
            elif m := re.match(r"/api/posts/(\d+)/metricas$", path):
                post_id = int(m.group(1))
                result = registrar_metricas(post_id, data)
                json_response(self, result)
            elif m := re.match(r"/api/posts/(\d+)/publish$", path):
                post_id = int(m.group(1))
                result = publish_post(post_id)
                json_response(self, result)
            elif m := re.match(r"/api/smartlinks/(\d+)/click$", path):
                link_id = int(m.group(1))
                result = track_smartlink_click(link_id)
                json_response(self, result)
            elif m := re.match(r"/api/comments/([^/]+)/reply$", path):
                comment_id = m.group(1)
                result = reply_to_comment(comment_id, data.get("message"))
                json_response(self, result)
            elif path == "/api/integrations/instagram/sync":
                limit = parse_int(data.get("limit", 25), "limit", default=25, minimum=1)
                result = sync_instagram_posts_and_metrics(limit=min(limit, 100))
                json_response(self, result)
            else:
                json_response(self, {"error": "Ruta no encontrada"}, 404)
        except ValueError as e:
            json_response(self, {"error": str(e)}, 400)
        except LookupError as e:
            json_response(self, {"error": str(e)}, 404)
        except Exception:
            traceback.print_exc()
            json_response(self, {"error": "Error interno del servidor"}, 500)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            json_response(self, {"error": "JSON inválido"}, 400)
            return

        path = urlparse(self.path).path
        if m := re.match(r"/api/posts/(\d+)$", path):
            post_id = int(m.group(1))
            try:
                result = editar_post(post_id, data)
                json_response(self, result)
            except ValueError as e:
                json_response(self, {"error": str(e)}, 400)
            except LookupError as e:
                json_response(self, {"error": str(e)}, 404)
            except Exception:
                json_response(self, {"error": "Error interno del servidor"}, 500)
        elif m := re.match(r"/api/smartlinks/(\d+)$", path):
            link_id = int(m.group(1))
            try:
                result = edit_smartlink(link_id, data)
                json_response(self, result)
            except ValueError as e:
                json_response(self, {"error": str(e)}, 400)
            except LookupError as e:
                json_response(self, {"error": str(e)}, 404)
            except Exception:
                json_response(self, {"error": "Error interno del servidor"}, 500)
        else:
            json_response(self, {"error": "Ruta no encontrada"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if m := re.match(r"/api/posts/(\d+)$", path):
            post_id = int(m.group(1))
            try:
                result = eliminar_post(post_id)
                json_response(self, result)
            except LookupError as e:
                json_response(self, {"error": str(e)}, 404)
            except Exception:
                json_response(self, {"error": "Error interno del servidor"}, 500)
        else:
            json_response(self, {"error": "Ruta no encontrada"}, 404)


if __name__ == "__main__":
    init_db()
    port = 8000
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║        SocialPulse - Backend API         ║
╠══════════════════════════════════════════╣
║  Servidor corriendo en:                  ║
║  → http://localhost:{port}                  ║
║                                          ║
║  Abre el navegador en esa dirección      ║
║  para ver la aplicación.                 ║
║                                          ║
║  Ctrl+C para detener                     ║
╚══════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Servidor detenido.")
