import pandas as pd
import json
import requests # Necesario para hacer llamadas a la API

class WeeklyTikTokAgent:
    """
    Agente que automatiza el análisis de rendimiento de TikTok
    y genera nuevas ideas de contenido con una llamada real a la API de Gemini.
    """
    def run(self, csv_path="Anonymized_Ad_Performance.csv"):
        print("--- Agente de Growth y IA Iniciado ---")
        try:
            df = pd.read_csv(csv_path)
            print(f"Éxito: El archivo '{csv_path}' se ha cargado correctamente.")
        except FileNotFoundError:
            print(f"Error: No se encontró '{csv_path}'.")
            return

        ranked_df = self._rank_creatives(df.copy())
        print("\n--- Top 5 Creatividades de la Semana ---")
        print(ranked_df[['Ad name', 'Performance_Score', 'Conversions']].head())
        
        new_ideas = self._generate_real_ideas(ranked_df)
        if not new_ideas:
            print("\nNo se pudieron generar nuevas ideas. Finalizando el proceso.")
            return

        email_output = self._format_email_output(new_ideas)
        print("\n--- Correo Electrónico Final Generado ---")
        print(email_output)
        
        print("\n--- Agente Finalizado ---")

    def _rank_creatives(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica la fórmula de Performance_Score al DataFrame."""
        df['Clicks'] = df['CTR (destination)'] * df['Impressions']
        df['CPC (destination)'] = df.apply(lambda r: r['Cost'] / r['Clicks'] if r['Clicks'] > 0 else float('inf'), axis=1)
        df['Conversion Rate'] = df.apply(lambda r: r['Conversions'] / r['Impressions'] * 100 if r['Impressions'] > 0 else 0, axis=1)

        for col in ['CTR (destination)', 'Conversion Rate', 'CPC (destination)']:
            min_val, max_val = df[col].min(), df[col].max()
            df[f'{col}_norm'] = (df[col] - min_val) / (max_val - min_val) if (max_val - min_val) > 0 else 0
        
        weights = {'ctr': 0.3, 'conv': 0.5, 'cpc': 0.2}
        df['Performance_Score'] = (weights['ctr'] * df['CTR (destination)_norm']) + \
                                  (weights['conv'] * df['Conversion Rate_norm']) - \
                                  (weights['cpc'] * df['CPC (destination)_norm'])
        
        return df.sort_values(by='Performance_Score', ascending=False)

    def _generate_real_ideas(self, ranked_df: pd.DataFrame) -> list | None:
        """Construye el prompt y llama a la API de Gemini para obtener ideas reales."""
        description_col_name = 'Text' 

        try:
            top_performers = ranked_df.head(2)
            insights = "Patrones de éxito identificados esta semana:\n"
            for _, row in top_performers.iterrows():
                insights += f"- Video '{row['Ad name']}' (Descripción: '{row[description_col_name]}'). Patrón: Contenido directo, UGC, o consejos financieros.\n"
        except KeyError:
            print(f"\nError: La columna '{description_col_name}' no se encontró.")
            return None

        print("\n--- Construyendo Prompt para la API de Gemini ---")
        prompt = self._build_prompt(insights)
        print(prompt)

        return self._call_gemini_api(prompt)

    def _build_prompt(self, insights: str) -> str:
        """Construye el prompt final para enviar a la API."""
        return f"""
        Eres un estratega de contenido experto en TikTok para la marca Fintech dedicada a dar prestamos en linea rapidos y seguros "Beloz", dirigida a jóvenes en México.
        **Análisis de Datos Reales (Input):**
        {insights}
        **Tu Tarea:**
        Basado en estos patrones de éxito reales, genera 3 nuevas ideas de video para TikTok. Las ideas deben ser creativas, muy específicas y culturalmente relevantes para México. Deben resaltar la facilidad, seguridad y confianza de usar Beloz.
        **Formato de Salida Obligatorio (JSON):**
        Responde únicamente con un objeto JSON que contenga una sola clave "ideas", la cual debe ser una lista de 3 objetos. Cada objeto debe tener estas tres claves exactas: "idea_title", "hook", "video_concept".
        """

    def _call_gemini_api(self, prompt: str) -> list | None:
        """Llama a la API de Gemini. Devuelve la lista de ideas o None si hay un error."""
        
        # --- ¡PASO CLAVE! PEGA TU API KEY AQUÍ ---
        API_KEY = "AIzaSyB9FJdawm27wVFomV3SHFIRE8KViJhOViQ"

        if API_KEY == "PEGA_AQUÍ_TU_CLAVE_DE_API_DE_GEMINI":
            print("\nERROR: Por favor, reemplaza 'PEGA_AQUÍ_TU_CLAVE_DE_API_DE_GEMINI' con tu clave real en el script.")
            return None

        print("\n[Real] Llamando a la API de Gemini con tu clave...")
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={API_KEY}"
        
        json_schema = {"type": "OBJECT","properties": {"ideas": {"type": "ARRAY","items": {"type": "OBJECT","properties": {"idea_title": {"type": "STRING"},"hook": {"type": "STRING"},"video_concept": {"type": "STRING"}},"required": ["idea_title", "hook", "video_concept"]}}},"required": ["ideas"]}
        payload = {"contents": [{"role": "user","parts": [{"text": prompt}]}],"generationConfig": {"response_mime_type": "application/json","response_schema": json_schema}}

        try:
            response = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            response_json = response.json()
            ideas_text = response_json['candidates'][0]['content']['parts'][0]['text']
            ideas_data = json.loads(ideas_text)
            print("\n[Real] ¡Éxito! Respuesta de la API recibida y procesada correctamente.")
            return ideas_data.get("ideas", [])
        except requests.exceptions.RequestException as e:
            print(f"\nError de conexión al llamar a la API de Gemini: {e}")
            return None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"\nError al procesar la respuesta de la API: {e}")
            print("Respuesta recibida del servidor:", response.text)
            return None

    def _format_email_output(self, ideas: list) -> str:
        """Crea el cuerpo del correo con las ideas generadas."""
        ideas_html = ""
        for i, idea in enumerate(ideas):
            ideas_html += f"<h4>Idea {i+1}: {idea.get('idea_title', 'N/A')}</h4><p><strong>Hook:</strong> {idea.get('hook', 'N/A')}</p><p><strong>Concepto:</strong> {idea.get('video_concept', 'N/A')}</p><hr>"
        
        email_template = f"""
        **Asunto:** 🚀 3 Nuevas Ideas de TikTok (Generadas por IA) para esta Semana
        **Para:** alejandro@amiloz.com, equipo.creativo@belozfi.com.mx
        Hola equipo,
        El agente de IA ha analizado el rendimiento y ha generado nuevas propuestas de contenido.
        **Nuevas Propuestas Creativas (Generadas por Gemini 1.5):**
        {ideas_html}
        Por favor, revisen las propuestas.
        Saludos,
        Agente de Growth y IA de Beloz
        """
        return email_template

if __name__ == '__main__':
    agent = WeeklyTikTokAgent()
    agent.run()