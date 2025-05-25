# Prompts

GitHub Copilot 
- https://www.youtube.com/watch?v=H3M95i4iS5c
- Use @workspace, ask me series of questions in yes/no format
- Use #filename to provide context and ask questions
- Give me 3 ways to connect to a database in Node.js. List pros and cons for each
- chain of thoughts - use "Refactor this file one change at a time. Wait for me to say next before continuing."
- AI loves to play the role "Act as a senior dev. Teach me regex step-by-step. Wait for my response before proceeding."

### Prompt Suggestions Based on These Strategies
🔹 Q&A Strategy Prompt
“I have a monolithic Node.js app. Can you ask me questions to help break it into modules?”

“Help me write a CI/CD pipeline. Ask me clarifying questions first.”

🔹 Pros & Cons Prompt
“Compare Express and Fastify for a high-concurrency API. List pros and cons.”

“What are the trade-offs between using Redis vs. in-memory caching in my app?”

🔹 Stepwise Chain of Thought Prompt
“Refactor this JavaScript code one step at a time. Wait for next after each change.”

“Walk me through setting up authentication with JWT, one step at a time.”

🔹 Role Prompt
“You are a coding mentor. Teach me how Promises work in JavaScript, step-by-step. Quiz me as we go.”

“Act as a DevOps engineer. Help me optimize my Dockerfile, one step at a time.”


