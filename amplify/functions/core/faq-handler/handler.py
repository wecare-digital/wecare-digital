"""
FAQ Handler Lambda Function

Purpose: Keyword-based FAQ search and response system
Cost: FREE - no external dependencies, no OpenSearch, no model calls
"""

import os
import json
import logging
from typing import Dict, Any, List, Tuple

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# Load FAQ configuration
from static_knowledge_base import FAQ_CONFIG


def search_faqs(query: str, max_results: int = 3, short_answer: bool = False) -> List[Dict]:
    """
    Search FAQs using keyword matching.
    
    Args:
        query: User's question
        max_results: Maximum number of results
        short_answer: Return short answers instead of full answers
        
    Returns:
        List of matching FAQ entries with scores
    """
    query_lower = query.lower()
    matches = []
    
    # Check for greetings first
    greeting_keywords = FAQ_CONFIG.get('greetings', {}).get('keywords', [])
    if any(keyword in query_lower for keyword in greeting_keywords):
        return [{
            'id': 'greeting',
            'question': 'Greeting',
            'answer': FAQ_CONFIG['greetings']['response'],
            'score': 100,
            'category': 'general'
        }]
    
    # Score each FAQ based on keyword matches
    for faq in FAQ_CONFIG['faqs']:
        score = 0
        matched_keywords = []
        
        for keyword in faq['keywords']:
            if keyword.lower() in query_lower:
                score += 1
                matched_keywords.append(keyword)
        
        if score > 0:
            matches.append({
                'id': faq['id'],
                'question': faq['question'],
                'answer': faq['shortAnswer'] if short_answer else faq['answer'],
                'score': score,
                'category': faq['category'],
                'matchedKeywords': matched_keywords
            })
    
    # Sort by score (highest first)
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    return matches[:max_results]


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    FAQ Handler - keyword-based search.
    
    Query params:
        - query: Search query
        - maxResults: Max results (default 3)
        - shortAnswer: Return short answers (default false)
        - category: Filter by category
    """
    request_id = context.aws_request_id if context else 'local'
    origin = extract_origin(event)
    headers = cors_headers(origin)
    
    # Handle OPTIONS
    if event.get('httpMethod') == 'OPTIONS' or event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth
    
    # Get query parameters
    params = event.get('queryStringParameters') or {}
    query = params.get('query', '')
    max_results = int(params.get('maxResults', 3))
    short_answer = params.get('shortAnswer', 'false').lower() == 'true'
    category_filter = params.get('category', '')
    
    logger.info(json.dumps({
        'event': 'faq_search',
        'query': query[:100],
        'maxResults': max_results,
        'shortAnswer': short_answer,
        'category': category_filter,
        'requestId': request_id
    }))
    
    if not query:
        # Return all FAQs grouped by category
        faqs_by_category = {}
        for faq in FAQ_CONFIG['faqs']:
            cat = faq['category']
            if cat not in faqs_by_category:
                faqs_by_category[cat] = []
            faqs_by_category[cat].append({
                'id': faq['id'],
                'question': faq['question'],
                'answer': faq['shortAnswer'] if short_answer else faq['answer'],
                'category': cat
            })
        
        return cors_response(200, {
            'faqs': faqs_by_category,
            'brand': FAQ_CONFIG['brand'],
            'categories': {
                'general': 'General Information',
                'orders': 'Orders & Delivery',
                'payments': 'Payments & Billing'
            }
        }, origin)
    
    # Search FAQs
    results = search_faqs(query, max_results, short_answer)
    
    # Filter by category if specified
    if category_filter:
        results = [r for r in results if r['category'] == category_filter]
    
    # Build response
    if not results:
        response_text = FAQ_CONFIG['defaultResponse']
    elif len(results) == 1:
        response_text = results[0]['answer']
    else:
        response_text = '\n\n'.join([f"Q: {r['question']}\nA: {r['answer']}" for r in results])
    
    logger.info(json.dumps({
        'event': 'faq_search_complete',
        'resultsCount': len(results),
        'requestId': request_id
    }))
    
    return cors_response(200, {
        'query': query,
        'results': results,
        'responseText': response_text,
        'brand': FAQ_CONFIG['brand']
    }, origin)
