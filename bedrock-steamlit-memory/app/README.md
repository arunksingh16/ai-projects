# Steamlit with memory

This chat app can retain history of chat and provide whole context to model everytime. e.g. -

`Every time the user sends a new prompt, the messages list in st.session_state (which contains the entire chat history) is sent to the Bedrock Claude endpoint. This is how the assistant keeps context across turns — but it means you're sending the full chat so far with every request.`