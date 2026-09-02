from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
import os

def follow_up_question_agent(agent, user_query, rag_response):
    if agent.llm_provider == "OpenAI":
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise EnvironmentError("Missing OPENAI_API_KEY")

        llm = ChatOpenAI(
            temperature=0,
            model=agent.llm_model,
            openai_api_key=openai_key
        )
    else:
        raise Exception(f"Unsupported LLM provider: {agent.llm_provider}")

    # Generic prompt template
    followup_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an intelligent assistant helping users explore their data more effectively. Once an answer has been provided for the user's original query, your next task is to suggest 2-3 relevant and insightful follow-up questions.

    These follow-up questions should:
    - Be relevant to the original user query and the provided answer.
    - Encourage deeper analysis, comparisons, or identification of trends, outliers, or root causes.
    - Reflect awareness of the domain based on context (e.g., HR, finance, sales, operations, healthcare, manufacturing, etc.).
    - Use terms or concepts that align with the user’s query or the data schema when possible.
    - Be phrased naturally, as if a helpful data analyst or business consultant is guiding the user.

    Example:
    User Query: "Show employee attrition by department"
    Follow-Up Suggestions:
    Which department has the highest attrition rate over the last year?
    Is there a correlation between job satisfaction and attrition in any department?
    Which managers had the highest turnover in their teams?

    Return only the follow-up questions in plain text, no explanation, no markdown."""),
        ("user", "{user_query}"),
        ("assistant", "{rag_response}")
    ])

    # Create and run the chain
    chain = followup_prompt | llm | StrOutputParser()
    raw_output = chain.invoke({
        "user_query": user_query,
        "rag_response": rag_response
    })

    # Parse plain text output into a list
    followups = [line.strip("-• ").strip() for line in raw_output.strip().split("\n") if line.strip()]
    return followups
