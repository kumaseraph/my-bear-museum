/**
 * 熊熊博物館星星 API Worker
 * 用於儲存和同步所有用戶的星星標記
 */

export default {
  async fetch(request, env, ctx) {
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // GET /stars - 取得所有星星
    if (path === '/stars' && request.method === 'GET') {
      try {
        const stars = await env.KUMA_KV.get('starredBears', 'json');
        return new Response(JSON.stringify(stars || []), {
          headers: {
            'Content-Type': 'application/json',
            ...corsHeaders,
          },
        });
      } catch (error) {
        return new Response(JSON.stringify({ error: error.message }), {
          status: 500,
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      }
    }

    // POST /stars - 更新星星列表
    if (path === '/stars' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { stars } = body;
        
        if (!Array.isArray(stars)) {
          return new Response(JSON.stringify({ error: 'Invalid stars data' }), {
            status: 400,
            headers: { 'Content-Type': 'application/json', ...corsHeaders },
          });
        }

        await env.KUMA_KV.put('starredBears', JSON.stringify(stars));
        
        return new Response(JSON.stringify({ success: true, stars }), {
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      } catch (error) {
        return new Response(JSON.stringify({ error: error.message }), {
          status: 500,
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      }
    }

    // Fallback for other routes
    return new Response('熊熊博物館星星 API v1.0\n可用端點:\nGET /stars - 取得所有星星\nPOST /stars - 更新星星列表', {
      headers: { 'Content-Type': 'text/plain', ...corsHeaders },
    });
  },
};