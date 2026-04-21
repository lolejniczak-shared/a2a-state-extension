from google.adk.agents import Agent

from dotenv import load_dotenv
load_dotenv()

instruction = """
You are helpful AI assistant.
Here are details about user:
<UserContext>
{user_info}
</UserContext>

Answer the user's questions with professional depth and technical accuracy.
"""

root_agent = Agent(
    model="gemini-2.5-flash",
    name="specialist_agent",
    instruction=instruction
)