#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
艾宾浩斯记忆法则学习程序 - 网页版
基于Python内置HTTP服务器的本地Web应用
"""

import sqlite3
import json
import datetime
import argparse
import os
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import socketserver
from typing import List, Dict, Optional, Tuple

# 修复Python 3.12的datetime警告
sqlite3.register_adapter(datetime.datetime, lambda x: x.isoformat())
sqlite3.register_converter("TIMESTAMP", lambda x: datetime.datetime.fromisoformat(x.decode()))

class EbbinghausMemory:
    """艾宾浩斯记忆法则管理器"""
    
    def __init__(self, db_path: str = "memory.db"):
        self.db_path = db_path
        self.init_database()
        
        # 艾宾浩斯遗忘曲线间隔（天）
        self.review_intervals = [1, 2, 4, 7, 15, 30, 60, 120, 240]
    
    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 检查是否存在旧数据库，如果存在需要升级
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                content TEXT,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_reviewed TIMESTAMP,
                next_review TIMESTAMP,
                review_count INTEGER DEFAULT 0,
                difficulty INTEGER DEFAULT 1,
                easiness REAL DEFAULT 2.5,
                interval INTEGER DEFAULT 1,
                mastered BOOLEAN DEFAULT FALSE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                review_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                quality INTEGER,
                response_time INTEGER,
                FOREIGN KEY (item_id) REFERENCES memory_items (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_item(self, question: str, answer: str, category: str = "default") -> int:
        """添加新的记忆项目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        next_review = datetime.datetime.now() + datetime.timedelta(days=1)
        
        cursor.execute('''
            INSERT INTO memory_items (question, answer, category, next_review, content)
            VALUES (?, ?, ?, ?, ?)
        ''', (question, answer, category, next_review, f"Q: {question}\nA: {answer}"))
        
        item_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return item_id
    
    def get_due_items(self, limit: int = 20) -> List[Dict]:
        """获取到期需要复习的项目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.datetime.now()
        
        cursor.execute('''
            SELECT id, question, answer, category, review_count, difficulty, easiness
            FROM memory_items
            WHERE next_review <= ? AND mastered = FALSE
            ORDER BY next_review ASC
            LIMIT ?
        ''', (now, limit))
        
        items = []
        for row in cursor.fetchall():
            items.append({
                'id': row[0],
                'question': row[1],
                'answer': row[2],
                'category': row[3],
                'review_count': row[4],
                'difficulty': row[5],
                'easiness': row[6]
            })
        
        conn.close()
        return items
    
    def update_item_review(self, item_id: int, quality: int, response_time: int = 0):
        """更新记忆项目的复习结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取当前项目信息
        cursor.execute('''
            SELECT review_count, easiness, interval, difficulty
            FROM memory_items
            WHERE id = ?
        ''', (item_id,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        review_count, easiness, interval, difficulty = row
        
        # SM-2算法更新参数
        easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        easiness = max(1.3, min(easiness, 2.5))
        
        if quality >= 3:
            if review_count == 0:
                interval = 1
            elif review_count == 1:
                interval = 6
            else:
                interval = interval * easiness
                interval = min(interval, 365)  # 最大间隔1年
        else:
            interval = 1
        
        review_count += 1
        
        # 计算下次复习时间
        next_review = datetime.datetime.now() + datetime.timedelta(days=interval)
        
        # 检查是否已掌握
        mastered = (quality >= 4 and review_count >= 5)
        
        # 更新项目
        cursor.execute('''
            UPDATE memory_items
            SET review_count = ?, easiness = ?, interval = ?,
                next_review = ?, last_reviewed = CURRENT_TIMESTAMP,
                mastered = ?, difficulty = ?
            WHERE id = ?
        ''', (review_count, easiness, interval, next_review, mastered, 
              quality, item_id))
        
        # 记录复习历史
        cursor.execute('''
            INSERT INTO review_history (item_id, quality, response_time)
            VALUES (?, ?, ?)
        ''', (item_id, quality, response_time))
        
        conn.commit()
        conn.close()
    
    def get_all_items(self, category: str = None) -> List[Dict]:
        """获取所有记忆项目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute('''
                SELECT id, question, answer, category, review_count, mastered, next_review
                FROM memory_items
                WHERE category = ?
                ORDER BY created_at DESC
            ''', (category,))
        else:
            cursor.execute('''
                SELECT id, question, answer, category, review_count, mastered, next_review
                FROM memory_items
                ORDER BY created_at DESC
            ''')
        
        items = []
        for row in cursor.fetchall():
            items.append({
                'id': row[0],
                'question': row[1],
                'answer': row[2],
                'category': row[3],
                'review_count': row[4],
                'mastered': row[5],
                'next_review': row[6]
            })
        
        conn.close()
        return items
    
    def get_categories(self) -> List[str]:
        """获取所有分类"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT category FROM memory_items')
        categories = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return categories
    
    def delete_item(self, item_id: int):
        """删除记忆项目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM review_history WHERE item_id = ?', (item_id,))
        cursor.execute('DELETE FROM memory_items WHERE id = ?', (item_id,))
        
        conn.commit()
        conn.close()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        items = self.get_all_items()
        categories = self.get_categories()
        
        total = len(items)
        mastered = sum(1 for item in items if item['mastered'])
        due_count = len(self.get_due_items(limit=1000))
        
        category_stats = {}
        for category in categories:
            cat_items = [item for item in items if item['category'] == category]
            cat_mastered = sum(1 for item in cat_items if item['mastered'])
            category_stats[category] = {
                'total': len(cat_items),
                'mastered': cat_mastered
            }
        
        return {
            'total': total,
            'mastered': mastered,
            'due': due_count,
            'mastery_rate': round(mastered/total*100, 1) if total > 0 else 0,
            'categories': category_stats
        }

class MemoryHTTPRequestHandler(SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器"""
    
    def __init__(self, *args, **kwargs):
        self.memory = EbbinghausMemory()
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """处理GET请求"""
        if self.path == '/' or self.path == '/index.html':
            self.serve_index()
        elif self.path == '/api/due':
            self.serve_due_items()
        elif self.path == '/api/items':
            self.serve_all_items()
        elif self.path == '/api/stats':
            self.serve_stats()
        elif self.path == '/api/categories':
            self.serve_categories()
        else:
            super().do_GET()
    
    def do_POST(self):
        """处理POST请求"""
        if self.path == '/api/add':
            self.handle_add_item()
        elif self.path == '/api/review':
            self.handle_review()
        elif self.path == '/api/delete':
            self.handle_delete()
        else:
            self.send_error(404)
    
    def serve_index(self):
        """服务主页"""
        html_content = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>艾宾浩斯记忆法则学习程序</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .nav {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
        }
        
        .nav button {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            background: #667eea;
            color: white;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s ease;
        }
        
        .nav button:hover {
            background: #5a6fd8;
            transform: translateY(-2px);
        }
        
        .nav button.active {
            background: #764ba2;
        }
        
        .content {
            padding: 30px;
        }
        
        .section {
            display: none;
        }
        
        .section.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
            color: #333;
        }
        
        .form-group textarea {
            width: 100%;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            font-size: 16px;
            resize: vertical;
            min-height: 120px;
        }
        
        .form-group input, .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            font-size: 16px;
        }
        
        .btn {
            background: #667eea;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 25px;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .btn:hover {
            background: #5a6fd8;
            transform: translateY(-2px);
        }
        
        .btn-danger {
            background: #dc3545;
        }
        
        .btn-danger:hover {
            background: #c82333;
        }
        
        .review-item {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            border-left: 5px solid #667eea;
        }
        
        .review-item h3 {
            color: #333;
            margin-bottom: 15px;
        }
        
        .review-item .meta {
            color: #666;
            font-size: 14px;
            margin-bottom: 15px;
        }
        
        .quality-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .quality-btn {
            padding: 8px 16px;
            border: 2px solid #667eea;
            background: white;
            color: #667eea;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .quality-btn:hover {
            background: #667eea;
            color: white;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 15px;
            text-align: center;
        }
        
        .stat-card h3 {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .item-list {
            max-height: 600px;
            overflow-y: auto;
        }
        
        .item-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 4px solid #667eea;
        }
        
        .item-card h4 {
            color: #333;
            margin-bottom: 10px;
        }
        
        .item-card .item-content {
            color: #666;
            margin-bottom: 10px;
            white-space: pre-wrap;
        }
        
        .item-card .item-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
            color: #999;
        }
        
        .success-message {
            background: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            border: 1px solid #c3e6cb;
        }
        
        .hidden {
            display: none;
        }
        
        @media (max-width: 768px) {
            .nav {
                flex-direction: column;
                align-items: center;
            }
            
            .nav button {
                width: 100%;
                max-width: 300px;
            }
            
            .quality-buttons {
                justify-content: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 艾宾浩斯记忆法则</h1>
            <p>科学记忆，高效学习</p>
        </div>
        
        <div class="nav">
            <button onclick="showSection('add', this)" class="active">添加内容</button>
            <button onclick="showSection('review', this)">开始复习</button>
            <button onclick="showSection('items', this)">所有内容</button>
            <button onclick="showSection('stats', this)">统计信息</button>
        </div>
        
        <div class="content">
            <div id="message" class="success-message hidden"></div>
            
            <!-- 添加内容 -->
            <div id="add-section" class="section active">
                <h2>添加新的学习内容</h2>
                <form id="add-form">
                    <div class="form-group">
                        <label for="question">问题：</label>
                        <textarea id="question" placeholder="请输入问题或知识点..." required></textarea>
                    </div>
                    <div class="form-group">
                        <label for="answer">答案：</label>
                        <textarea id="answer" placeholder="请输入答案或解释..." required></textarea>
                    </div>
                    <div class="form-group">
                        <label for="category">分类：</label>
                        <select id="category">
                            <option value="default">默认</option>
                            <option value="english">英语</option>
                            <option value="programming">编程</option>
                            <option value="science">科学</option>
                            <option value="history">历史</option>
                            <option value="other">其他</option>
                        </select>
                    </div>
                    <button type="submit" class="btn">添加内容</button>
                </form>
            </div>
            
            <!-- 复习 -->
            <div id="review-section" class="section">
                <h2>开始复习</h2>
                <div id="review-items"></div>
                <button onclick="loadReviewItems()" class="btn">加载复习内容</button>
            </div>
            
            <!-- 所有内容 -->
            <div id="items-section" class="section">
                <h2>所有学习内容</h2>
                <div id="items-list"></div>
                <button onclick="loadAllItems()" class="btn">刷新列表</button>
            </div>
            
            <!-- 统计信息 -->
            <div id="stats-section" class="section">
                <h2>统计信息</h2>
                <div id="stats-content"></div>
                <button onclick="loadStats()" class="btn">刷新统计</button>
            </div>
        </div>
    </div>
    
    <script>
        let currentReviewIndex = 0;
        let reviewItems = [];
        
        // 显示消息
        function showMessage(message) {
            const messageEl = document.getElementById('message');
            messageEl.textContent = message;
            messageEl.classList.remove('hidden');
            setTimeout(() => {
                messageEl.classList.add('hidden');
            }, 3000);
        }
        
        // 切换页面
        function showSection(sectionName, buttonElement = null) {
            // 隐藏所有section
            document.querySelectorAll('.section').forEach(section => {
                section.classList.remove('active');
            });
            
            // 移除所有按钮的active类
            document.querySelectorAll('.nav button').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // 显示目标section
            document.getElementById(sectionName + '-section').classList.add('active');
            
            // 激活对应按钮
            if (buttonElement) {
                buttonElement.classList.add('active');
            } else {
                // 如果没有传入按钮元素，找到对应的按钮
                const buttons = document.querySelectorAll('.nav button');
                buttons.forEach(btn => {
                    if (btn.textContent.includes(getSectionTitle(sectionName))) {
                        btn.classList.add('active');
                    }
                });
            }
            
            // 根据页面类型自动加载内容
            if (sectionName === 'review') {
                loadReviewItems();
            } else if (sectionName === 'items') {
                loadAllItems();
            } else if (sectionName === 'stats') {
                loadStats();
            }
        }
        
        // 获取页面标题
        function getSectionTitle(sectionName) {
            const titles = {
                'add': '添加内容',
                'review': '开始复习',
                'items': '所有内容',
                'stats': '统计信息'
            };
            return titles[sectionName] || '';
        }
        
        // 添加内容
        document.getElementById('add-form').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const question = document.getElementById('question').value;
            const answer = document.getElementById('answer').value;
            const category = document.getElementById('category').value;
            
            fetch('/api/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    question: question,
                    answer: answer,
                    category: category
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showMessage('内容添加成功！');
                    document.getElementById('add-form').reset();
                } else {
                    showMessage('添加失败：' + data.error);
                }
            })
            .catch(error => {
                showMessage('网络错误');
            });
        });
        
        // 加载复习内容
        function loadReviewItems() {
            fetch('/api/due')
            .then(response => response.json())
            .then(data => {
                reviewItems = data;
                currentReviewIndex = 0;
                displayReviewItem();
            })
            .catch(error => {
                showMessage('✗ 加载复习内容失败');
            });
        }
        
        // 显示复习项目
        function displayReviewItem() {
            const container = document.getElementById('review-items');
            
            if (currentReviewIndex >= reviewItems.length) {
                container.innerHTML = '<h3>复习完成！</h3><p>今天没有更多需要复习的内容了。</p>';
                return;
            }
            
            const item = reviewItems[currentReviewIndex];
            container.innerHTML = `
                <div class="review-item">
                    <h3>问题 ${currentReviewIndex + 1} / ${reviewItems.length}</h3>
                    <div class="meta">
                        分类：${item.category} | 复习次数：${item.review_count}
                    </div>
                    <div style="background: white; padding: 20px; border-radius: 10px; margin: 15px 0;">
                        <h4>问题：</h4>
                        <div style="white-space: pre-wrap; margin: 10px 0; font-size: 18px; color: #333;">${item.question}</div>
                    </div>
                    <div id="answer-section-${item.id}" style="display: none;">
                        <div style="background: #e8f5e8; padding: 20px; border-radius: 10px; margin: 15px 0;">
                            <h4>答案：</h4>
                            <div style="white-space: pre-wrap; margin: 10px 0; font-size: 16px; color: #555;">${item.answer}</div>
                        </div>
                        <p><strong>请评估你的记忆质量：</strong></p>
                        <div class="quality-buttons">
                            <button class="quality-btn" onclick="submitReview(${item.id}, 1)">完全忘记</button>
                            <button class="quality-btn" onclick="submitReview(${item.id}, 2)">模糊记得</button>
                            <button class="quality-btn" onclick="submitReview(${item.id}, 3)">基本记得</button>
                            <button class="quality-btn" onclick="submitReview(${item.id}, 4)">完全记得</button>
                            <button class="quality-btn" onclick="submitReview(${item.id}, 5)">非常熟练</button>
                        </div>
                    </div>
                    <div id="show-answer-btn-${item.id}">
                        <button class="btn" onclick="showAnswer(${item.id})">显示答案</button>
                    </div>
                </div>
            `;
        }
        
        // 显示答案
        function showAnswer(itemId) {
            document.getElementById(`answer-section-${itemId}`).style.display = 'block';
            document.getElementById(`show-answer-btn-${itemId}`).style.display = 'none';
        }
        
        // 提交复习结果
        function submitReview(itemId, quality) {
            fetch('/api/review', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    item_id: itemId,
                    quality: quality
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    currentReviewIndex++;
                    displayReviewItem();
                } else {
                    showMessage('✗ 提交失败：' + data.error);
                }
            })
            .catch(error => {
                showMessage('✗ 网络错误');
            });
        }
        
        // 加载所有内容
        function loadAllItems() {
            fetch('/api/items')
            .then(response => response.json())
            .then(data => {
                const container = document.getElementById('items-list');
                
                if (data.length === 0) {
                    container.innerHTML = '<p>还没有添加任何内容</p>';
                    return;
                }
                
                container.innerHTML = data.map(item => `
                    <div class="item-card">
                        <h4>[${item.category}]</h4>
                        <div class="item-content">
                            <strong>问题：</strong>
                            <div style="margin: 8px 0; padding: 10px; background: #f0f8ff; border-radius: 5px;">${item.question}</div>
                            <strong>答案：</strong>
                            <div style="margin: 8px 0; padding: 10px; background: #f0fff0; border-radius: 5px;">${item.answer}</div>
                        </div>
                        <div class="item-meta">
                            <span>复习次数：${item.review_count} | ${item.mastered ? '✓ 已掌握' : '学习中'}</span>
                            <button class="btn btn-danger" onclick="deleteItem(${item.id})">删除</button>
                        </div>
                    </div>
                `).join('');
            })
            .catch(error => {
                showMessage('✗ 加载内容失败');
            });
        }
        
        // 删除项目
        function deleteItem(itemId) {
            if (confirm('确定要删除这个项目吗？')) {
                fetch('/api/delete', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        item_id: itemId
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage('✓ 删除成功');
                        loadAllItems();
                        loadStats();
                    } else {
                        showMessage('✗ 删除失败：' + data.error);
                    }
                })
                .catch(error => {
                    showMessage('✗ 网络错误');
                });
            }
        }
        
        // 加载统计信息
        function loadStats() {
            fetch('/api/stats')
            .then(response => response.json())
            .then(data => {
                const container = document.getElementById('stats-content');
                
                container.innerHTML = `
                    <div class="stats-grid">
                        <div class="stat-card">
                            <h3>${data.total}</h3>
                            <p>总项目数</p>
                        </div>
                        <div class="stat-card">
                            <h3>${data.mastered}</h3>
                            <p>已掌握</p>
                        </div>
                        <div class="stat-card">
                            <h3>${data.due}</h3>
                            <p>待复习</p>
                        </div>
                        <div class="stat-card">
                            <h3>${data.mastery_rate}%</h3>
                            <p>掌握率</p>
                        </div>
                    </div>
                    <h3>分类统计</h3>
                    <div class="stats-grid">
                        ${Object.entries(data.categories).map(([category, stats]) => `
                            <div class="stat-card">
                                <h3>${category}</h3>
                                <p>${stats.total} 项 (已掌握 ${stats.mastered} 项)</p>
                            </div>
                        `).join('')}
                    </div>
                `;
            })
            .catch(error => {
                showMessage('✗ 加载统计失败');
            });
        }
        
        // 页面加载时初始化
        window.addEventListener('load', function() {
            loadStats();
        });
    </script>
</body>
</html>
        '''
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def serve_due_items(self):
        """服务到期复习项目"""
        items = self.memory.get_due_items()
        self.send_json_response(items)
    
    def serve_all_items(self):
        """服务所有项目"""
        items = self.memory.get_all_items()
        self.send_json_response(items)
    
    def serve_stats(self):
        """服务统计信息"""
        stats = self.memory.get_stats()
        self.send_json_response(stats)
    
    def serve_categories(self):
        """服务分类列表"""
        categories = self.memory.get_categories()
        self.send_json_response(categories)
    
    def handle_add_item(self):
        """处理添加项目请求"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            question = data.get('question', '')
            answer = data.get('answer', '')
            category = data.get('category', 'default')
            
            if not question.strip() or not answer.strip():
                self.send_json_response({'success': False, 'error': '问题和答案都不能为空'})
                return
            
            item_id = self.memory.add_item(question, answer, category)
            self.send_json_response({'success': True, 'item_id': item_id})
            
        except Exception as e:
            self.send_json_response({'success': False, 'error': str(e)})
    
    def handle_review(self):
        """处理复习请求"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            item_id = data.get('item_id')
            quality = data.get('quality')
            
            if not item_id or quality not in [1, 2, 3, 4, 5]:
                self.send_json_response({'success': False, 'error': '参数错误'})
                return
            
            self.memory.update_item_review(item_id, quality)
            self.send_json_response({'success': True})
            
        except Exception as e:
            self.send_json_response({'success': False, 'error': str(e)})
    
    def handle_delete(self):
        """处理删除请求"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            item_id = data.get('item_id')
            
            if not item_id:
                self.send_json_response({'success': False, 'error': '参数错误'})
                return
            
            self.memory.delete_item(item_id)
            self.send_json_response({'success': True})
            
        except Exception as e:
            self.send_json_response({'success': False, 'error': str(e)})
    
    def send_json_response(self, data):
        """发送JSON响应"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def log_message(self, format, *args):
        """禁用日志输出"""
        pass

def run_server(port=8000, auto_open=True):
    """运行HTTP服务器"""
    handler = MemoryHTTPRequestHandler
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        print("艾宾浩斯记忆程序已启动")
        print(f"请在浏览器中访问: http://localhost:{port}")
        print("按 Ctrl+C 停止服务器")
        
        if auto_open:
            # 延迟1秒打开浏览器，确保服务器已启动
            threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{port}')).start()
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='艾宾浩斯记忆法则学习程序 - 网页版')
    parser.add_argument('--port', type=int, default=8000, help='端口号 (默认: 8000)')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    
    args = parser.parse_args()
    
    run_server(port=args.port, auto_open=not args.no_browser)