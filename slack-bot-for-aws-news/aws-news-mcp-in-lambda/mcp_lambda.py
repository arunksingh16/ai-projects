import json

class McpLambdaServer:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def decorator(fn):
            tool_name = name or fn.__name__
            self.tools[tool_name] = fn
            return fn
        return decorator

    def handle(self, event, context):
        body = event.get("body", "")
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode()

        request = json.loads(body)

        method = request.get("method")
        req_id = request.get("id")

        if method == "tools/list":
            return self._response(req_id, {
                "tools": [{"name": k} for k in self.tools.keys()]
            })

        if method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})

            if name not in self.tools:
                return self._error(req_id, f"Unknown tool: {name}")

            try:
                result = self.tools[name](**args)
                return self._response(req_id, result)
            except Exception as e:
                return self._error(req_id, str(e))

        return self._error(req_id, f"Unknown method: {method}")

    def _response(self, req_id, result):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "jsonrpc": "2.0",
                "result": result,
                "id": req_id
            })
        }

    def _error(self, req_id, message):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "jsonrpc": "2.0",
                "error": {"message": message},
                "id": req_id
            })
        }
