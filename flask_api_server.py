"""
Flask API Server - Bot va Dashboard Bridge
Bu server bot va HTML dashboard o'rtasida API sifatida ishlaydi
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import logging
from datetime import datetime
from typing import Dict, List
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pubg_bot_v2 import (
    get_registered_users,
    bot,
    active_matches,
    tournament_data,
    start_tournament,
    end_tournament,
    ADMIN_ID
)

app = Flask(__name__)
CORS(app)  

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_async(coro):
    """Run async function in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/api/get_players', methods=['GET'])
def get_players():
    """Get all registered players"""
    try:
        users = run_async(get_registered_users())
        
        return jsonify({
            'success': True,
            'players': users,
            'tournament_active': tournament_data['active'],
            'tournament_start': tournament_data['start_time'].isoformat() if tournament_data['start_time'] else None,
            'total_count': len(users)
        })
    except Exception as e:
        logger.exception("get_players error")
        return jsonify({
            'success': False,
            'error': str(e),
            'players': []
        }), 500

@app.route('/api/send_lobby', methods=['POST'])
def send_lobby():
    """Send lobby info to selected players"""
    try:
        data = request.json
        lobby_id = data.get('lobby_id', '')
        password = data.get('password', '')
        players = data.get('players', [])
        
        if not lobby_id or len(lobby_id) != 7 or not lobby_id.isdigit():
            return jsonify({
                'success': False,
                'error': 'Lobby ID 7 ta raqamdan iborat bo\'lishi kerak'
            }), 400
        
        if not password or len(password) < 4:
            return jsonify({
                'success': False,
                'error': 'Parol kamida 4 ta belgidan iborat bo\'lishi kerak'
            }), 400
        
        if not players or len(players) < 2:
            return jsonify({
                'success': False,
                'error': 'Kamida 2 ta o\'yinchi tanlash kerak'
            }), 400
        
        run_async(start_tournament())
        
        sent_count = 0
        failed_users = []
        
        async def send_to_players():
            nonlocal sent_count, failed_users
            
            for player in players:
                try:
                    others = [p for p in players if p['telegram_id'] != player['telegram_id']]
                    opponents = ", ".join([p['nickname'] for p in others])
                    
                    text = (
                        f"🎮 <b>YANGI O'YIN BOSHLANDI!</b>\n\n"
                        f"👥 <b>Raqiblaringiz:</b>\n{opponents}\n\n"
                        f"🆔 <b>Lobby ID:</b> <code>{lobby_id}</code>\n"
                        f"🔐 <b>Parol:</b> <code>{password}</code>\n\n"
                        f"⏰ <b>Tezroq o'yinga kiring!</b>\n"
                        f"🏆 Omad tilaymiz!"
                    )
                    
                    await bot.send_message(player['telegram_id'], text)
                    sent_count += 1
                    await asyncio.sleep(0.1)  
                    
                except Exception as e:
                    logger.warning(f"Failed to send to {player['telegram_id']}: {e}")
                    failed_users.append(player['nickname'])
        
        run_async(send_to_players())
        
        match_id = f"MATCH_{len(active_matches) + 1}_{int(datetime.now().timestamp())}"
        active_matches[match_id] = {
            'match_id': match_id,
            'lobby_id': lobby_id,
            'password': password,
            'players': players,
            'created_at': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'sent_count': sent_count,
            'total': len(players),
            'failed': failed_users,
            'match_id': match_id
        })
        
    except Exception as e:
        logger.exception("send_lobby error")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/end_tournament', methods=['POST'])
def api_end_tournament():
    """End tournament and cleanup data"""
    try:
        run_async(end_tournament(auto=False))
        
        return jsonify({
            'success': True,
            'message': 'Turnir yakunlandi va ma\'lumotlar tozalandi'
        })
    except Exception as e:
        logger.exception("end_tournament error")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tournament_status', methods=['GET'])
def tournament_status():
    """Get tournament status"""
    try:
        remaining_time = None
        
        if tournament_data['active'] and tournament_data['start_time']:
            elapsed = datetime.now() - tournament_data['start_time']
            remaining_seconds = (24 * 60 * 60) - elapsed.total_seconds()
            
            if remaining_seconds > 0:
                hours = int(remaining_seconds // 3600)
                minutes = int((remaining_seconds % 3600) // 60)
                remaining_time = f"{hours}s {minutes}d"
        
        return jsonify({
            'success': True,
            'tournament_active': tournament_data['active'],
            'start_time': tournament_data['start_time'].isoformat() if tournament_data['start_time'] else None,
            'remaining_time': remaining_time,
            'active_matches': len(active_matches)
        })
    except Exception as e:
        logger.exception("tournament_status error")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/matches', methods=['GET'])
def get_matches():
    """Get all active matches"""
    try:
        matches_list = [
            {
                'match_id': match_id,
                'lobby_id': match['lobby_id'],
                'password': match['password'],
                'players': match['players'],
                'created_at': match['created_at']
            }
            for match_id, match in active_matches.items()
        ]
        
        return jsonify({
            'success': True,
            'matches': matches_list,
            'count': len(matches_list)
        })
    except Exception as e:
        logger.exception("get_matches error")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'bot_running': True
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint topilmadi'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Server xatosi'
    }), 500

if __name__ == '__main__':
    logger.info("🚀 Flask API Server ishga tushmoqda...")
    logger.info("📡 Dashboard uchun API tayyor")
    logger.info("🔗 Endpoints:")
    logger.info("  GET  /api/get_players")
    logger.info("  POST /api/send_lobby")
    logger.info("  POST /api/end_tournament")
    logger.info("  GET  /api/tournament_status")
    logger.info("  GET  /api/matches")
    logger.info("  GET  /api/health")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )