import threading
import requests
import time
import json

BASE_URL = "http://localhost:8000"

def test_concurrent_writes():
    print("🚀 Iniciando prueba de ESCRITURA CONCURRENTE (SQLite Stress Test)...")
    results = []
    
    def create_post(i):
        data = {
            "fecha": "2026-03-28",
            "tipo_contenido": "educativo",
            "objetivo": "visibilidad",
            "tema": f"Test Concurrente {i}",
            "cta": "Click aquí",
            "descripcion": "Verificando que no haya bloqueos de BD",
            "interacciones_esperadas": 100
        }
        try:
            resp = requests.post(f"{BASE_URL}/api/posts", json=data)
            results.append(resp.status_code)
        except Exception as e:
            results.append(f"Error: {str(e)}")

    threads = []
    for i in range(20): # 20 peticiones simultáneas
        t = threading.Thread(target=create_post, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    success = results.count(201)
    errors = len(results) - success
    print(f"📊 Resultados: {success} éxitos, {errors} errores.")
    if errors == 0:
        print("✅ SQLite con gestores de contexto es ROBUSTO.")
    else:
        print("❌ Se detectaron fallos de concurrencia.")

def test_sync_graceful_failure():
    print("\n🔍 Verificando blindaje de SINCRONIZACIÓN (Sin credenciales)...")
    try:
        # Esto debería fallar por falta de token, pero capturarse como un 400 o 500 controlado.
        # El punto es ver si el servidor sigue vivo después.
        resp = requests.post(f"{BASE_URL}/api/integrations/instagram/sync", json={"limit": 5})
        print(f"📡 Respuesta Sync: {resp.status_code} - {resp.json()}")
        print("✅ El servidor manejó el fallo de API de forma controlada.")
    except Exception as e:
        print(f"❌ El servidor murió o devolvió error no capturado: {str(e)}")

if __name__ == "__main__":
    # Esperar un poco a que el servidor levante
    time.sleep(2)
    try:
        test_concurrent_writes()
        test_sync_graceful_failure()
        print("\n🏆 PRUEBAS DE ESTABILIDAD COMPLETADAS.")
    except Exception as e:
        print(f"CRITICAL FAIL: {str(e)}")
