# AI Agent with Streamlit Interface

A comprehensive AI agent built with LangChain and Streamlit, featuring Azure OpenAI integration, conversational memory, cost tracking, and configurable logging.

## 🚀 Features

- **Multi-Model Support**: Runtime model selection with JSON configuration
- **Conversational Memory**: Full conversation context maintained across interactions
- **Cost Tracking**: Real-time cost monitoring with detailed token usage
- **Configurable Logging**: Adjustable logging levels and output formats
- **Streaming Responses**: Simulated streaming with complete metadata capture
- **Model Configuration**: JSON-based model management with temperature handling
- **Comprehensive Metadata**: Azure OpenAI response metadata and usage tracking

## 📋 Prerequisites

- Python 3.8+
- Azure OpenAI account with deployed models
- Required environment variables (see Configuration section)

## 🛠️ Installation

1. **Clone or download the project files**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   ```bash
   export AZURE_OPENAI_API_KEY="your-api-key"
   export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com/"
   ```

4. **Configure models** (optional):
   - Edit `model_configs.json` to add/remove models
   - See Model Configuration section for details

## 🚀 Usage

### Running the Streamlit App

```bash
streamlit run streamlit_app.py
```

The app will open in your browser at `http://localhost:8501`

### Running the Basic Agent

```bash
python agent.py
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `AZURE_OPENAI_API_KEY` | Your Azure OpenAI API key | Yes | - |
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI endpoint URL | Yes | - |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No | INFO |
| `ENABLE_CONVERSATION_LOG` | Enable JSON conversation logging | No | true |
| `ENABLE_DETAILED_LOGGING` | Enable detailed metadata logging | No | true |
| `LOG_FILE_PATH` | Path for log files | No | ai_agent.log |

### Model Configuration

Edit `model_configs.json` to configure available models:

```json
{
  "models": {
    "gpt-4o": {
      "name": "GPT-4o",
      "deployment_name": "gpt-4o",
      "api_version": "2025-01-01-preview",
      "model_version": "2024-08-06",
      "temperature": 0.0,
      "supports_temperature": true,
      "description": "Latest GPT-4o model with full temperature support"
    }
  },
  "default_model": "gpt-4o"
}
```

### Logging Configuration

The app supports multiple logging configurations:

#### 1. Environment Variable Control
```bash
export LOG_LEVEL=DEBUG
export ENABLE_CONVERSATION_LOG=false
export ENABLE_DETAILED_LOGGING=true
```

#### 2. Runtime Configuration
Use the sidebar controls in the Streamlit app to adjust logging behavior.

## 📊 Logging Features

### Log Types

1. **Console Logs** (`ai_agent.log`):
   - Interaction summaries
   - Cost tracking
   - Error messages
   - Debug information

2. **Conversation Logs** (`conversation_log.json`):
   - Complete conversation history
   - Full response metadata
   - Token usage details
   - Model information

### Logging Levels

- **DEBUG**: Detailed debugging information
- **INFO**: General information about operations
- **WARNING**: Warning messages for non-critical issues
- **ERROR**: Error messages for critical failures

### Metadata Captured

- **Token Usage**: Input, output, and total tokens
- **Cost Information**: Real-time cost tracking
- **Model Details**: Model name, version, deployment info
- **Response Metadata**: Azure OpenAI response details
- **Content Filters**: Safety filter results
- **System Information**: Fingerprints and service tiers

## 🎯 Usage Examples

### Basic Chat
1. Select a model from the dropdown
2. Type your message in the chat input
3. View the response and cost information

### Cost Monitoring
- View real-time costs in the sidebar
- Track total session costs
- Monitor average cost per interaction

### Model Switching
- Change models during conversation
- Each model maintains separate configurations
- Temperature and other parameters handled automatically

## 🔧 Advanced Features

### Conversational Memory
- Full conversation context maintained
- Memory persists across model switches
- Clear memory option available

### Cost Tracking
- Real-time cost calculation
- Token usage monitoring
- Historical cost data

### Error Handling
- Graceful model initialization
- Temperature parameter fallbacks
- JSON file corruption recovery

## 📁 File Structure

```
AIAgent/
├── agent.py                 # Basic agent script
├── streamlit_app.py         # Main Streamlit application
├── model_configs.json       # Model configuration
├── requirements.txt         # Python dependencies
├── README.md               # This documentation
├── ai_agent.log            # Console logs (generated)
└── conversation_log.json   # Conversation logs (generated)
```

## 🐛 Troubleshooting

### Common Issues

1. **Model Not Found Error**:
   - Check `model_configs.json` for correct deployment names
   - Verify Azure OpenAI deployment exists

2. **Temperature Not Supported**:
   - Some models don't support temperature parameters
   - The app automatically handles this

3. **Cost Tracking Shows $0.00**:
   - Ensure `model_version` is set in model configuration
   - Check Azure OpenAI API version compatibility

4. **JSON Parsing Errors**:
   - The app automatically recovers from corrupted log files
   - Check file permissions if issues persist

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
export LOG_LEVEL=DEBUG
streamlit run streamlit_app.py
```

## 🔒 Security Considerations

- Store API keys in environment variables
- Don't commit sensitive configuration to version control
- Regularly rotate API keys
- Monitor usage and costs

## 📈 Performance Tips

- Use appropriate model for your use case
- Monitor token usage to optimize prompts
- Clear conversation memory for long sessions
- Use cost tracking to manage expenses

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs for error details
3. Create an issue with detailed information

## 🔄 Updates

### Version 1.0.0
- Initial release with basic functionality
- Azure OpenAI integration
- Streamlit interface
- Cost tracking
- Conversational memory

### Future Enhancements
- Additional model providers
- Advanced analytics dashboard
- Export functionality
- API endpoint creation
