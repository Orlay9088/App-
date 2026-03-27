# SocialPulse — Gestión de Contenido en Redes Sociales

## Instalación y ejecución

### Requisitos
- Python 3.7 o superior (sin dependencias externas)

### Pasos para iniciar

1. Coloca `app.py` e `index.html` en la misma carpeta
2. Abre una terminal en esa carpeta
3. Ejecuta:

```bash
python app.py
```

4. Abre tu navegador en: **http://localhost:8000**

La base de datos `socialpulse.db` (SQLite) se crea automáticamente en la misma carpeta.

---

## Flujo de uso semanal

| Día       | Acción                              |
|-----------|-------------------------------------|
| Lunes     | Crear post → guardar en sistema     |
| Miércoles | Crear post → guardar en sistema     |
| Viernes   | Crear post → guardar en sistema     |
| Domingo   | Ir a "Registrar Métricas" → ingresar datos |

---

## Vistas del sistema

- **Dashboard** — resumen general + insights + últimos posts
- **Nuevo Post** — formulario para planificar publicaciones
- **Mis Posts** — tabla completa con estado y métricas
- **Registrar Métricas** — ingreso rápido de datos del domingo
- **Calendario** — vista mensual con días de publicación (L-M-V) y medición (D)
- **Análisis** — gráficas de rendimiento por tipo de contenido y día

---

## Índice de interacción (puntuación ponderada)

```
Likes × 1 + Comentarios × 2 + Compartidos × 3 + Guardados × 4 + DMs × 5
```

Los guardados y DMs tienen mayor peso porque indican mayor intención del usuario.

---

## API REST

| Método | Ruta                          | Descripción              |
|--------|-------------------------------|--------------------------|
| GET    | /api/posts                    | Obtener todos los posts  |
| POST   | /api/posts                    | Crear nuevo post         |
| DELETE | /api/posts/:id                | Eliminar post            |
| POST   | /api/posts/:id/metricas       | Registrar/actualizar métricas |
| GET    | /api/analisis                 | Obtener análisis agregados |
| GET    | /api/integrations/instagram/status | Estado de conexión con Instagram |
| POST   | /api/integrations/instagram/sync   | Sincroniza posts y métricas reales de Instagram |

---

## Conectar Instagram (datos reales)

Configura estas variables de entorno antes de correr `python app.py`:

- `INSTAGRAM_BUSINESS_ACCOUNT_ID`
- `INSTAGRAM_ACCESS_TOKEN`

Ejemplo en PowerShell:

```powershell
$env:INSTAGRAM_BUSINESS_ACCOUNT_ID="TU_ID_DE_CUENTA_BUSINESS"
$env:INSTAGRAM_ACCESS_TOKEN="TU_TOKEN_DE_GRAPH_API"
python app.py
```

Luego abre `http://localhost:8000` y en Dashboard usa el botón **Sincronizar IG**.
