import os
import sys
from pathlib import Path

# Add project root to sys.path so we can import backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.agents.config import get_agent_settings, LLMFactory

def main():
    print("============================================================")
    print("VEXA REAL LLM PROVIDER SMOKE TEST")
    print("============================================================")

    # Load agent settings (reads from environment variables including .env)
    settings = get_agent_settings()
    
    print(f"Configured Provider: {settings.llm_provider}")
    print(f"Configured Model:    {settings.llm_model}")
    print(f"Execution Mode:      {settings.llm_mode}")
    
    if settings.llm_mode != "real":
        print("\n[WARNING] llm_mode is not 'real'. Smoke test will still attempt to initialize the real provider using LLMFactory.")

    print("\nInitializing LLM...")
    try:
        llm = LLMFactory.build(settings)
        print("✅ LLM Factory successfully built the LLM instance.")
    except Exception as e:
        print(f"❌ LLM Factory Failed: {e}")
        print("Please check your API keys and provider configuration.")
        sys.exit(1)

    print("\nSending a test prompt to the LLM...")
    
    prompt = "Hello! Please reply with exactly one word: 'READY'."
    
    try:
        # The CrewAI LLM wrapper exposes call methods. Depending on version, it might be .call or direct invocation
        if hasattr(llm, "call"):
            response = llm.call(messages=[{"role": "user", "content": prompt}])
        else:
            # Fallback to liteLLM directly if crewai LLM wrapper doesn't have an easy public sync method
            # but usually they do. Let's try calling it.
            import litellm
            messages = [{"role": "user", "content": prompt}]
            
            api_key = settings.llm_api_key
            if not api_key:
                provider = settings.llm_provider.lower()
                if provider == "openai":
                    api_key = os.environ.get("OPENAI_API_KEY")
                elif provider == "anthropic":
                    api_key = os.environ.get("ANTHROPIC_API_KEY")
                elif provider == "mistral":
                    api_key = os.environ.get("MISTRAL_API_KEY")
                elif provider == "gemini":
                    api_key = os.environ.get("GEMINI_API_KEY")
                elif provider == "groq":
                    api_key = os.environ.get("GROQ_API_KEY")
                    
            response = litellm.completion(
                model=settings.llm_model,
                messages=messages,
                api_key=api_key,
                temperature=0.1
            )
            
            content = response.choices[0].message.content.strip()
            usage = response.usage
            print("\n============================================================")
            print("SMOKE TEST SUCCESSFUL")
            print("============================================================")
            print(f"Response:      {content}")
            print(f"Input Tokens:  {usage.prompt_tokens if usage else 'N/A'}")
            print(f"Output Tokens: {usage.completion_tokens if usage else 'N/A'}")
            print(f"Total Tokens:  {usage.total_tokens if usage else 'N/A'}")
            print("============================================================")

    except Exception as e:
        print(f"\n❌ Provider request failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
