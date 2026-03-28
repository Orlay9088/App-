import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_validation():
    print("🧪 Probando VALIDACIÓN de API...")
    
    # 1. Probar fecha inválida
    data = {
        "fecha": "2026-13-45", # Fecha inexistente
        "tipo_contenido": "educativo",
        "objetivo": "visibilidad",
        "tema": "Test Fecha Inválida",
        "cta": "Click",
        "image_url": "https://example.com/img.jpg"
    }
    headers = {"X-API-Key": "4f645d656f59152b9dd9e2b944be344d466a292071c7cff3"}
    resp = requests.post(f"{BASE_URL}/api/posts", json=data, headers=headers)
    print(f"📅 Fecha inválida: {resp.status_code} - {resp.json().get('error')}")
    assert resp.status_code == 400

    # 2. Probar URL de imagen inválida
    data["fecha"] = "2026-03-28"
    data["image_url"] = "not-a-url"
    resp = requests.post(f"{BASE_URL}/api/posts", json=data, headers=headers)
    print(f"🖼️ URL imagen inválida: {resp.status_code} - {resp.json().get('error')}")
    assert resp.status_code == 400

    # 3. Probar SmartLink con URL inválida
    data_sl = {
        "titulo": "My Link",
        "url": "javascript:alert(1)"
    }
    resp = requests.post(f"{BASE_URL}/api/smartlinks", json=data_sl, headers=headers)
    print(f"🔗 SmartLink URL inválida: {resp.status_code} - {resp.json().get('error')}")
    assert resp.status_code == 400

    # 4. Probar éxito con datos válidos
    data["image_url"] = "https://picsum.photos/200"
    resp = requests.post(f"{BASE_URL}/api/posts", json=data, headers=headers)
    print(f"✅ Éxito con datos válidos: {resp.status_code}")
    assert resp.status_code == 201

if __name__ == "__main__":
    try:
        test_validation()
        print("\n✅ TODAS LAS PRUEBAS DE VALIDACIÓN PASARON.")
    except Exception as e:
        print(f"❌ FALLO EN LAS PRUEBAS: {e}")
