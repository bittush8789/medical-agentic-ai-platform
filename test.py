from app.agent import graph 


config = {"configurable": {"thread_id": "user_123"}}

result = graph.invoke(
    {
        "question": "What causes headaches?",
        "history": [],
        "image_description": "",
        "kb": [],
        "web": [],
        "answer": "",
        "route": "",
        "model": ""
    },
    config=config
)

print("Final Result:", result)