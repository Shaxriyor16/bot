#!/bin/bash

# ========================================
# PUBG Tournament Bot Deployment Scripts
# ========================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🎮 PUBG Tournament Bot Deployment${NC}"
echo "===================================="

# ========================================
# 1. INSTALL DEPENDENCIES
# ========================================
install_dependencies() {
    echo -e "${YELLOW}📦 Installing dependencies...${NC}"
    
    # Create virtual environment
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo -e "${GREEN}✅ Virtual environment created${NC}"
    fi
    
    # Activate venv
    source venv/bin/activate
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install requirements
    pip install -r requirements.txt
    
    echo -e "${GREEN}✅ Dependencies installed${NC}"
}

# ========================================
# 2. CHECK ENVIRONMENT
# ========================================
check_environment() {
    echo -e "${YELLOW}🔍 Checking environment...${NC}"
    
    if [ ! -f ".env" ]; then
        echo -e "${RED}❌ .env file not found!${NC}"
        echo "Creating .env template..."
        cat > .env << EOF
BOT_TOKEN=your_bot_token_here
ADMIN_ID=7337873747
REQUIRED_CHANNELS=@M24SHaxa_youtube
SHEET_JSON_CONTENT={"your":"json","here":"..."}
EOF
        echo -e "${YELLOW}⚠️  Please fill .env file with your credentials${NC}"
        exit 1
    fi
    
    # Check if BOT_TOKEN is set
    source .env
    if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "your_bot_token_here" ]; then
        echo -e "${RED}❌ BOT_TOKEN not configured in .env${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Environment configured${NC}"
}

# ========================================
# 3. START BOT
# ========================================
start_bot() {
    echo -e "${YELLOW}🤖 Starting Telegram Bot...${NC}"
    
    # Kill existing bot process
    pkill -f "python.*pubg_bot_v2.py" 2>/dev/null
    
    # Start bot in background
    nohup python pubg_bot_v2.py > bot.log 2>&1 &
    BOT_PID=$!
    
    sleep 3
    
    if ps -p $BOT_PID > /dev/null; then
        echo -e "${GREEN}✅ Bot started (PID: $BOT_PID)${NC}"
        echo "Bot logs: tail -f bot.log"
    else
        echo -e "${RED}❌ Bot failed to start. Check bot.log${NC}"
        exit 1
    fi
}

# ========================================
# 4. START API SERVER
# ========================================
start_api() {
    echo -e "${YELLOW}🌐 Starting API Server...${NC}"
    
    # Kill existing API process
    pkill -f "python.*flask_api_server.py" 2>/dev/null
    
    # Start API in background
    nohup python flask_api_server.py > api.log 2>&1 &
    API_PID=$!
    
    sleep 3
    
    if ps -p $API_PID > /dev/null; then
        echo -e "${GREEN}✅ API Server started (PID: $API_PID)${NC}"
        echo "API logs: tail -f api.log"
        echo "API URL: http://localhost:5000"
    else
        echo -e "${RED}❌ API failed to start. Check api.log${NC}"
        exit 1
    fi
}

# ========================================
# 5. STOP ALL SERVICES
# ========================================
stop_services() {
    echo -e "${YELLOW}🛑 Stopping all services...${NC}"
    
    pkill -f "python.*pubg_bot_v2.py" 2>/dev/null
    pkill -f "python.*flask_api_server.py" 2>/dev/null
    
    sleep 2
    
    echo -e "${GREEN}✅ All services stopped${NC}"
}

# ========================================
# 6. CHECK STATUS
# ========================================
check_status() {
    echo -e "${YELLOW}📊 Service Status:${NC}"
    echo "===================="
    
    # Check bot
    if pgrep -f "python.*pubg_bot_v2.py" > /dev/null; then
        BOT_PID=$(pgrep -f "python.*pubg_bot_v2.py")
        echo -e "Bot:        ${GREEN}✅ Running${NC} (PID: $BOT_PID)"
    else
        echo -e "Bot:        ${RED}❌ Stopped${NC}"
    fi
    
    # Check API
    if pgrep -f "python.*flask_api_server.py" > /dev/null; then
        API_PID=$(pgrep -f "python.*flask_api_server.py")
        echo -e "API Server: ${GREEN}✅ Running${NC} (PID: $API_PID)"
    else
        echo -e "API Server: ${RED}❌ Stopped${NC}"
    fi
    
    echo "===================="
}

# ========================================
# 7. VIEW LOGS
# ========================================
view_logs() {
    echo -e "${YELLOW}📜 Recent logs:${NC}"
    echo "===================="
    
    if [ -f "bot.log" ]; then
        echo -e "${GREEN}Bot Logs (last 20 lines):${NC}"
        tail -n 20 bot.log
    fi
    
    echo ""
    
    if [ -f "api.log" ]; then
        echo -e "${GREEN}API Logs (last 20 lines):${NC}"
        tail -n 20 api.log
    fi
}

# ========================================
# 8. RESTART SERVICES
# ========================================
restart_services() {
    stop_services
    sleep 2
    start_bot
    start_api
}

# ========================================
# 9. SETUP SYSTEMD (Optional)
# ========================================
setup_systemd() {
    echo -e "${YELLOW}⚙️  Setting up systemd services...${NC}"
    
    CURRENT_DIR=$(pwd)
    VENV_PYTHON="$CURRENT_DIR/venv/bin/python"
    
    # Bot service
    sudo tee /etc/systemd/system/pubg-bot.service > /dev/null << EOF
[Unit]
Description=PUBG Tournament Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$CURRENT_DIR
Environment="PATH=$CURRENT_DIR/venv/bin"
ExecStart=$VENV_PYTHON pubg_bot_v2.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # API service
    sudo tee /etc/systemd/system/pubg-api.service > /dev/null << EOF
[Unit]
Description=PUBG Tournament API Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$CURRENT_DIR
Environment="PATH=$CURRENT_DIR/venv/bin"
ExecStart=$VENV_PYTHON flask_api_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable services
    sudo systemctl enable pubg-bot.service
    sudo systemctl enable pubg-api.service
    
    echo -e "${GREEN}✅ Systemd services configured${NC}"
    echo ""
    echo "Commands:"
    echo "  sudo systemctl start pubg-bot"
    echo "  sudo systemctl start pubg-api"
    echo "  sudo systemctl status pubg-bot"
    echo "  sudo systemctl status pubg-api"
}

# ========================================
# MAIN MENU
# ========================================
show_menu() {
    echo ""
    echo "===================================="
    echo "Select an option:"
    echo "===================================="
    echo "1) Install dependencies"
    echo "2) Start all services"
    echo "3) Stop all services"
    echo "4) Restart all services"
    echo "5) Check status"
    echo "6) View logs"
    echo "7) Setup systemd (optional)"
    echo "8) Full deployment (1 + 2)"
    echo "9) Exit"
    echo "===================================="
}

# ========================================
# MAIN EXECUTION
# ========================================
main() {
    while true; do
        show_menu
        read -p "Enter choice [1-9]: " choice
        
        case $choice in
            1)
                install_dependencies
                ;;
            2)
                check_environment
                start_bot
                start_api
                check_status
                ;;
            3)
                stop_services
                ;;
            4)
                restart_services
                ;;
            5)
                check_status
                ;;
            6)
                view_logs
                ;;
            7)
                setup_systemd
                ;;
            8)
                install_dependencies
                check_environment
                start_bot
                start_api
                check_status
                echo ""
                echo -e "${GREEN}🎉 Deployment complete!${NC}"
                echo ""
                echo "Next steps:"
                echo "1. Open dashboard.html in browser"
                echo "2. Configure API_BASE in dashboard"
                echo "3. Start using the bot!"
                ;;
            9)
                echo -e "${GREEN}Goodbye! 👋${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option${NC}"
                ;;
        esac
        
        echo ""
        read -p "Press Enter to continue..."
    done
}

# Run main if script is executed directly
if [ "${BASH_SOURCE[0]}" -eq "${0}" ]; then
    main
fi