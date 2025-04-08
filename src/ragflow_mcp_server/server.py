import os
import logging
import json
import click
import asyncio
from typing import Optional, Dict, Any
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
from ragflow_sdk import RAGFlow
from dotenv import load_dotenv


logger = logging.getLogger('ragflow_mcp_server')
logger.info("Starting RAGFlow MCP Server")

# 全局变量
ragflow: Optional[RAGFlow] = None
# 存储聊天会话的字典
active_sessions: Dict[str, Any] = {}


async def initialize_server(api_key:str, base_url: str):
    """初始化 RAGFlow MCP 服务器"""
    global ragflow
    load_dotenv()

    api_key = api_key or os.getenv("RAGFLOW_API_KEY")
    base_url = base_url or os.getenv("RAGFLOW_BASE_URL")

    if not api_key or not base_url:
        raise ValueError("RAGFLOW_API_KEY and RAGFLOW_BASE_URL environment variables must be set")

    ragflow = RAGFlow(api_key=api_key, base_url=base_url)


async def serve() -> Server:
    server = Server("ragflow-mcp-server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """处理工具列表请求"""
        return [
            types.Tool(
                name="list_datasets",
                title="列出数据集",
                description="列出 RAGFlow 中的所有数据集",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
            ),
            types.Tool(
                name="create_chat",
                title="创建聊天",
                description="创建一个新的聊天助手，基于指定的数据集",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "dataset_id": {
                            "type": "string", 
                            "description": "数据集ID"
                        },
                        "name": {
                            "type": "string", 
                            "description": "聊天助手的名称，可选，默认为'RAGFlow助手'"
                        }
                    },
                    "required": ["dataset_id"]
                },
            ),
            types.Tool(
                name="chat",
                title="聊天",
                description="向聊天助手提问",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string", 
                            "description": "聊天会话ID"
                        },
                        "question": {
                            "type": "string", 
                            "description": "提问的问题"
                        }
                    },
                    "required": ["session_id", "question"]
                },
            )
        ]
        
    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """处理工具调用请求"""
        if not ragflow:
            raise ValueError("RAGFlow client is not initialized")
            
        if name == "list_datasets":
            # 获取参数，使用默认值
            dataset_id = arguments.get("id", None) if arguments else None
            dataset_name = arguments.get("name", None) if arguments else None
            
            try:
                # 调用 RAGFlow SDK
                datasets = ragflow.list_datasets()
                
                # 只返回 id 和 name 属性
                result = [{"id": ds.id, "name": ds.name} for ds in datasets]
                
                # 返回格式化的 JSON 结果
                return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error: {str(e)}")]
        
        elif name == "create_chat":
            if not arguments:
                return [types.TextContent(type="text", text="Error: 未提供参数")]
                
            dataset_id = arguments.get("dataset_id")
            chat_name = arguments.get("name", "RAGFlow助手")
            
            if not dataset_id:
                return [types.TextContent(type="text", text="Error: 必须提供数据集ID")]
                
            try:
                # 获取数据集
                datasets = ragflow.list_datasets(id=dataset_id)
                if not datasets:
                    return [types.TextContent(type="text", text=f"Error: 找不到ID为 {dataset_id} 的数据集")]
                
                # 创建聊天助手
                assistant = ragflow.create_chat(name=chat_name, dataset_ids=[dataset_id])
                
                # 创建会话
                session = assistant.create_session(name=f"{chat_name}会话")
                
                # 存储会话信息
                session_id = session.id
                active_sessions[session_id] = session
                
                result = {
                    "session_id": session_id,
                    "chat_id": assistant.id,
                    "name": chat_name
                }
                
                return [types.TextContent(type="text", text=f"已创建聊天会话。请使用以下会话ID进行对话：\n\n{json.dumps(result, ensure_ascii=False, indent=2)}")]
                
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error: 创建聊天会话失败 - {str(e)}")]
        
        elif name == "chat":
            if not arguments:
                return [types.TextContent(type="text", text="Error: 未提供参数")]
                
            session_id = arguments.get("session_id")
            question = arguments.get("question")
            
            if not session_id or not question:
                return [types.TextContent(type="text", text="Error: 必须提供会话ID和问题")]
                
            if session_id not in active_sessions:
                return [types.TextContent(type="text", text=f"Error: 找不到ID为 {session_id} 的会话，请先创建会话")]
                
            try:
                session = active_sessions[session_id]
                
                response = ""
                for ans in session.ask(question, stream=True):
                    response = ans.content
                
                if not response:
                    return [types.TextContent(text="Error: 未收到任何响应")]
                
                # 直接返回回答    
                return [types.TextContent(type="text", text=response)]

            except Exception as e:
                return [types.TextContent(type="text", text=f"Error: 处理问题时出错 - {str(e)}")]
                
        return []

    return server

# def main(auth_token: str):
#     async def _run():
#         async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
#             server = await serve(auth_token)
#             await server.run(
#                 read_stream,
#                 write_stream,
#                 InitializationOptions(
#                     server_name="sentry",
#                     server_version="0.4.1",
#                     capabilities=server.get_capabilities(
#                         notification_options=NotificationOptions(),
#                         experimental_capabilities={},
#                     ),
#                 ),
#             )

#     asyncio.run(_run())

@click.command()
@click.option(
    "--api-key",
    envvar="RAGFLOW_API_KEY",
    required=True,
    help="RAGFlow API key"
)
@click.option(
    "--base-url",
    envvar="RAGFLOW_BASE_URL",
    required=True,
    help="RAGFlow base URL"
)
def main(api_key: str, base_url: str):
    async def _run():
        await initialize_server(api_key, base_url)
        
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            server = await serve()
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="ragflow-mcp-server",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    asyncio.run(_run())
