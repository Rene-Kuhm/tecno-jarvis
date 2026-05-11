from core.config import get_api_key


def get_live_client():
    from google import genai
    return genai.Client(
        api_key=get_api_key(),
        http_options={"api_version": "v1beta"},
    )


def get_text_model(model_name: str, system_instruction: str = None):
    import google.generativeai as genai
    genai.configure(api_key=get_api_key())
    return genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction,
    )


def generate_text(model_name: str, prompt: str, system_instruction: str = None) -> str:
    model = get_text_model(model_name, system_instruction)
    response = model.generate_content(prompt)
    return response.text.strip()


def get_live_types():
    from google.genai import types
    return types
