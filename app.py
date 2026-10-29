"""
Marketplace Ivinhema - versão com correções de segurança.

VARIÁVEIS DE AMBIENTE (obrigatórias):
    SUPABASE_URL, SUPABASE_KEY
    SECRET_KEY        -> python -c "import secrets; print(secrets.token_hex(32))"
    ADMIN_USER        -> usuário do Basic Auth do painel admin
    ADMIN_PASSWORD    -> senha do Basic Auth do painel admin (use uma NOVA, forte)
    ADMIN_EMAIL       -> e-mail da conta que é admin no site

VARIÁVEIS OPCIONAIS:
    USAR_HTTPS=1      -> marca cookies como Secure e envia HSTS (use quando o site estiver em HTTPS)
    TRUST_PROXY=1     -> use quando estiver atrás de Nginx/Render/Railway etc. (IP real e host corretos)
    HOST / PORT       -> só para `python app.py` (padrão 127.0.0.1:5000)
    FLASK_DEBUG=1     -> NUNCA ligar em produção
"""
import hmac
import ipaddress
import logging
import math
import os
import random
import re
import secrets
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   jsonify, Response, send_from_directory, abort)
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from flask_moment import Moment
from PIL import Image, ImageOps
from supabase import create_client, Client
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("marketplace")


# ============================================================
# CONFIGURAÇÃO
# ============================================================
def _env_bool(nome, padrao=False):
    return os.environ.get(nome, "1" if padrao else "0").strip().lower() in ("1", "true", "sim", "yes")


USAR_HTTPS = _env_bool("USAR_HTTPS")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    log.warning("SECRET_KEY não definida: usando chave aleatória temporária "
                "(todos serão deslogados a cada reinício). Defina SECRET_KEY no ambiente!")

ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").lower().strip()
if not (ADMIN_USER and ADMIN_PASSWORD and ADMIN_EMAIL):
    log.warning("ADMIN_USER / ADMIN_PASSWORD / ADMIN_EMAIL não definidos: painel admin DESATIVADO.")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Defina SUPABASE_URL e SUPABASE_KEY no ambiente.")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
if _env_bool("TRUST_PROXY"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SECRET_KEY=SECRET_KEY,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB por requisição
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=USAR_HTTPS,
    REMEMBER_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=USAR_HTTPS,
    SESSION_COOKIE_SAMESITE='Lax',
    BABEL_DEFAULT_LOCALE='pt_br',
)

Image.MAX_IMAGE_PIXELS = 40_000_000  # proteção contra "decompression bomb"

moment = Moment(app)
fuso_ivinhema = timezone(timedelta(hours=-4))

CIDADES_MS = sorted(['Ivinhema', 'Angélica', 'Novo Horizonte', 'Deodápolis',
                     'Dourados', 'Naviraí', 'Nova Andradina'])

PROIBIDAS = ['caralho', 'porra', 'merda', 'essa puta', 'vigarista', 'golpe',
             'urubu do pix', 'ladrão', 'admin', 'lula', 'bolsonaro']

FORMATOS_IMAGEM_OK = {'JPEG', 'PNG', 'WEBP', 'GIF'}

if os.path.exists('/data'):
    BASE_DIR = '/data'
    UPLOAD_FOLDER = '/data/uploads'
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['IMAGENS_SISTEMA'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# UTILITÁRIOS DE SEGURANÇA
# ============================================================
_tentativas = {}
_tentativas_lock = threading.Lock()


def ip_cliente():
    return request.remote_addr or 'desconhecido'


def excedeu_limite(chave, maximo, janela, registrar=True):
    """Rate limit simples em memória (por processo). True = passou do limite."""
    agora = time.time()
    with _tentativas_lock:
        if len(_tentativas) > 20000:
            for k in [k for k, v in _tentativas.items() if not v or agora - v[-1] > 86400]:
                _tentativas.pop(k, None)
        lista = [t for t in _tentativas.get(chave, []) if agora - t < janela]
        if len(lista) >= maximo:
            _tentativas[chave] = lista
            return True
        if registrar:
            lista.append(agora)
        _tentativas[chave] = lista
        return False


def origem_confiavel():
    """Anti-CSRF sem token: a requisição precisa vir do próprio site."""
    site = request.headers.get('Sec-Fetch-Site')
    if site:
        return site in ('same-origin', 'none')
    origem = request.headers.get('Origin') or request.headers.get('Referer')
    if not origem:
        return False
    try:
        return urlparse(origem).netloc == request.host
    except ValueError:
        return False


def exige_origem(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not origem_confiavel():
            abort(403)
        return f(*args, **kwargs)
    return decorated


@app.before_request
def proteger_contra_csrf():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not origem_confiavel():
        abort(403)


@app.after_request
def cabecalhos_de_seguranca(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    if USAR_HTTPS:
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return resp


@app.errorhandler(413)
def arquivo_grande(e):
    return "Arquivo muito grande (máximo 16 MB).", 413


def _comparar(a, b):
    return hmac.compare_digest((a or '').encode('utf-8'), (b or '').encode('utf-8'))


def admin_configurado():
    return bool(ADMIN_USER and ADMIN_PASSWORD and ADMIN_EMAIL)


def eh_o_vitor_logado():
    """True se o usuário logado no site é a conta admin (usado também nos templates)."""
    if not ADMIN_EMAIL or not current_user.is_authenticated:
        return False
    return _comparar((current_user.email or '').lower().strip(), ADMIN_EMAIL)


def basic_auth_admin_ok():
    auth = request.authorization
    if not auth or not admin_configurado():
        return False
    ok_user = _comparar(auth.username, ADMIN_USER)
    ok_pass = _comparar(auth.password, ADMIN_PASSWORD)
    return ok_user and ok_pass


def admin_autenticado():
    """Basic Auth correto E sessão logada com o e-mail do admin."""
    return basic_auth_admin_ok() and eh_o_vitor_logado()


def somente_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not admin_configurado():
            abort(404)
        ip = ip_cliente()
        if excedeu_limite(f"admin-bloq:{ip}", 10, 300, registrar=False):
            return Response('Muitas tentativas. Aguarde.', 429)
        if not basic_auth_admin_ok():
            excedeu_limite(f"admin-bloq:{ip}", 10, 300)  # registra a falha
            return Response('Acesso negado!', 401, {'WWW-Authenticate': 'Basic realm="Login"'})
        if not eh_o_vitor_logado():
            return redirect(url_for('exibir_mural'))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def injetar_funcoes_uteis():
    return dict(eh_o_vitor_logado=eh_o_vitor_logado)


def url_http_segura(url):
    """Retorna a URL se for http/https válida; senão ''. Barra javascript:, data:, etc."""
    if not isinstance(url, str):
        return ''
    url = url.strip()
    if not url or len(url) > 2000:
        return ''
    try:
        p = urlparse(url)
    except ValueError:
        return ''
    if p.scheme not in ('http', 'https') or not p.netloc:
        return ''
    return url


def url_publica(url):
    """Anti-SSRF: só permite http(s) nas portas 80/443 e que resolvam para IPs públicos."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https') or not p.hostname:
            return False
        porta = p.port or (443 if p.scheme == 'https' else 80)
        if porta not in (80, 443):
            return False
        infos = socket.getaddrinfo(p.hostname, porta, proto=socket.IPPROTO_TCP)
    except (ValueError, socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if not ip.is_global:
            return False
    return True


def buscar_html_seguro(url, max_redirects=4, max_bytes=1_000_000):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/'
    }
    atual = url
    for _ in range(max_redirects + 1):
        if not url_publica(atual):
            raise ValueError('URL não permitida.')
        r = requests.get(atual, headers=headers, timeout=10, allow_redirects=False, stream=True)
        if r.status_code in (301, 302, 303, 307, 308):
            destino = r.headers.get('Location')
            r.close()
            if not destino:
                raise ValueError('Redirecionamento inválido.')
            atual = urljoin(atual, destino)
            continue
        dados = bytearray()
        for pedaco in r.iter_content(8192):
            dados.extend(pedaco)
            if len(dados) > max_bytes:
                break
        codificacao = r.encoding or 'utf-8'
        r.close()
        return dados.decode(codificacao, errors='replace')
    raise ValueError('Redirecionamentos demais.')


def sanitizar_termo_busca(termo):
    """Remove caracteres que quebrariam/alterariam o filtro do PostgREST."""
    return re.sub(r'[,()*\\%]', ' ', termo or '')[:60].strip()


def parse_data(valor):
    if not valor:
        return None
    s = str(valor).replace('Z', '+00:00')
    s = re.sub(r'\.(\d+)', lambda m: '.' + (m.group(1) + '000000')[:6], s)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=fuso_ivinhema)
    return d


def converter_preco_br(valor):
    """'R$ 1.234,56' -> 1234.56 (formato brasileiro, usado no cadastro de anúncios)."""
    limpo = (valor or '').replace('R$', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
    if re.fullmatch(r'\d{1,9}(\.\d{1,2})?', limpo):
        return float(limpo)
    return 0.0


def converter_preco_simples(valor):
    """'49.90' ou '49,90' -> 49.9 (usado nos achadinhos). Rejeita NaN/inf."""
    try:
        v = float(str(valor or '0').strip().replace(',', '.'))
    except ValueError:
        return 0.0
    if math.isnan(v) or math.isinf(v) or v < 0 or v > 1_000_000_000:
        return 0.0
    return v


# ============================================================
# ARQUIVOS / UPLOADS
# ============================================================
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


def salvar_imagem(arq, tamanho=(800, 800), subpasta='', prefixo='foto'):
    """Valida, reprocessa e salva a imagem SEMPRE como .jpg com nome aleatório.
    Levanta ValueError se o arquivo não for uma imagem válida."""
    if not arq or not arq.filename:
        return None
    try:
        img = Image.open(arq.stream)
        if img.format not in FORMATOS_IMAGEM_OK:
            raise ValueError("formato não permitido")
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            log.warning("Erro ao corrigir orientação: %s", e)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            fundo.paste(img, mask=img.split()[-1])
            img = fundo
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail(tamanho, Image.Resampling.LANCZOS)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ValueError("Arquivo de imagem inválido.") from e

    nome = f"{prefixo}_{uuid.uuid4().hex}.jpg"
    pasta = os.path.join(UPLOAD_FOLDER, subpasta) if subpasta else UPLOAD_FOLDER
    os.makedirs(pasta, exist_ok=True)
    img.save(os.path.join(pasta, nome), format="JPEG", optimize=True, quality=85)
    return f"{subpasta}/{nome}" if subpasta else nome


def remover_arquivo_upload(nome):
    """Remove um arquivo de upload SOMENTE se estiver dentro da pasta de uploads."""
    if not nome or nome in ('sem-foto.jpg', 'default_perfil.png'):
        return
    if nome.startswith(('http://', 'https://')):
        return
    base = os.path.realpath(UPLOAD_FOLDER)
    caminho = os.path.realpath(os.path.join(base, nome))
    if not caminho.startswith(base + os.sep):
        log.warning("Tentativa de remover arquivo fora da pasta de uploads: %r", nome)
        return
    if os.path.isfile(caminho):
        try:
            os.remove(caminho)
        except OSError as e:
            log.warning("Erro ao remover arquivo %s: %s", caminho, e)


# ============================================================
# MODELOS
# ============================================================
class Usuario(UserMixin):
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.nome = kwargs.get('nome')
        self.foto_perfil = kwargs.get('foto_perfil', 'default_perfil.png')
        self.bairro = kwargs.get('bairro', 'Ivinhema')
        self.bio = kwargs.get('bio', "Vendedor verificado no Marketplace Ivinhema")
        self.whatsapp = kwargs.get('whatsapp')
        self.instagram = kwargs.get('instagram')
        self.data_cadastro = kwargs.get('data_cadastro')
        self.email = kwargs.get('email')
        self.senha = kwargs.get('senha')
        self.pedidos = kwargs.get('pedidos', [])
        self.link_afiliado = kwargs.get('link_afiliado', '#')

    def get_id(self):
        return str(self.id)


def criar_usuario_publico(dados, manter_email=False):
    """Cria Usuario SEM o hash da senha (e sem e-mail, salvo se pedido)."""
    dados = dict(dados or {})
    dados.pop('senha', None)
    if not manter_email:
        dados.pop('email', None)
    return Usuario(**dados)


class Pedido:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.titulo = kwargs.get('titulo')
        self.categoria = kwargs.get('categoria')
        self.descricao = kwargs.get('descricao')
        self.whatsapp = kwargs.get('whatsapp')
        self.local = kwargs.get('local')
        self.foto = kwargs.get('foto', 'sem-foto.jpg')
        self.foto2 = kwargs.get('foto2', '')
        self.foto3 = kwargs.get('foto3', '')
        self.data_criacao = kwargs.get('data_criacao')
        self.plano = kwargs.get('plano', 0)
        self.plano_aguardando = kwargs.get('plano_aguardando', 0)
        self.is_premium = kwargs.get('is_premium', False)
        self.preco = kwargs.get('preco')
        self.usuario_id = kwargs.get('usuario_id')
        self.acessos = kwargs.get('acessos', 0)
        self.denuncias = kwargs.get('denuncias', 0)
        self.verificado = kwargs.get('verificado', False)
        self.autor = kwargs.get('autor', None)
        self.plataforma = kwargs.get('plataforma') or 'nosso parceiro'
        # Só http/https: protege também registros antigos com "javascript:" no banco
        self.link_afiliado = url_http_segura(kwargs.get('link_afiliado')) or None
        self.is_afiliado = kwargs.get('is_afiliado', False)


class VendaEstatistica:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.categoria = kwargs.get('categoria')
        self.data_venda = kwargs.get('data_venda')


class Interesse:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.anuncio_id = kwargs.get('anuncio_id')
        self.comprador_id = kwargs.get('comprador_id')
        self.vendedor_id = kwargs.get('vendedor_id')
        self.data_solicitacao = kwargs.get('data_solicitacao')
        self.lido = kwargs.get('lido', False)
        self.anuncio = kwargs.get('anuncio', None)
        self.comprador = kwargs.get('comprador', None)


# ============================================================
# LIMPEZA DE ANÚNCIOS EXPIRADOS
# ============================================================
_ultima_limpeza = 0.0
_limpeza_lock = threading.Lock()


def limpar_expirados(forcar=False):
    """Remove anúncios vencidos. Roda no máximo 1x a cada 10 min por processo."""
    global _ultima_limpeza
    agora_ts = time.time()
    with _limpeza_lock:
        if not forcar and agora_ts - _ultima_limpeza < 600:
            return
        _ultima_limpeza = agora_ts

    agora = datetime.now(fuso_ivinhema)
    try:
        resp = supabase.table("pedido").select("id, data_expiracao, foto, foto2, foto3").execute()
        for p in (resp.data or []):
            vencimento = parse_data(p.get('data_expiracao'))
            if not vencimento or agora <= vencimento:
                continue
            for f in (p.get('foto'), p.get('foto2'), p.get('foto3')):
                remover_arquivo_upload(f)
            supabase.table("interesse").delete().eq("anuncio_id", p['id']).execute()
            supabase.table("pedido").delete().eq("id", p['id']).execute()
    except Exception:
        log.exception("Erro ao limpar expirados")


# ============================================================
# LOGIN
# ============================================================
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "faça o login para acessar esta página."
login_manager.login_message_category = "msg-alerta"

# Hash falso para igualar o tempo de resposta quando o e-mail não existe
_HASH_FALSO = generate_password_hash(secrets.token_hex(16))
EMAIL_RE = re.compile(r'[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s]{2,}')


@login_manager.user_loader
def load_user(user_id):
    try:
        resp = supabase.table("usuario").select("*").eq("id", int(user_id)).execute()
        if resp.data:
            dados = dict(resp.data[0])
            dados.pop('senha', None)  # a sessão não precisa do hash
            return Usuario(**dados)
    except Exception:
        log.exception("Erro ao carregar sessão do usuário")
    return None


# ============================================================
# VALIDAÇÃO DE ANÚNCIOS
# ============================================================
def validar_dados_anuncio(form, categoria_atual=None):
    titulo = (form.get('titulo') or '').strip()
    descricao = (form.get('descricao') or '').strip()
    categoria = (form.get('categoria') or '').strip()
    local = (form.get('local') or '').strip()

    if not titulo or len(titulo) > 100:
        return None, "Informe um título de até 100 caracteres."
    if len(descricao) > 2000:
        return None, "A descrição pode ter no máximo 2000 caracteres."
    if not categoria or len(categoria) > 40:
        return None, "Categoria inválida."
    if categoria == 'Achadinhos' and categoria_atual != 'Achadinhos':
        return None, "Categoria não permitida."
    if local not in CIDADES_MS:
        return None, "Cidade inválida."

    texto = f"{titulo} {descricao}".lower()
    for termo in PROIBIDAS:
        if termo in texto:
            return None, f"⚠️ O termo '{termo}' não é permitido."

    return {"titulo": titulo, "descricao": descricao, "categoria": categoria, "local": local}, None


# ============================================================
# ROTAS PRINCIPAIS
# ============================================================
@app.route('/cardapio_loja/<int:id_loja>')
def ver_cardapio_loja(id_loja):
    try:
        resp_loja = supabase.table("categorias").select("*").eq("id", id_loja).single().execute()
        loja_dados = resp_loja.data
        resp_itens = supabase.table("item_cardapio").select("*").eq("lanchonete_id", id_loja).execute()
        itens_dados = resp_itens.data if resp_itens.data else []
        return render_template('cardapio.html', lanchonete=loja_dados, itens=itens_dados)
    except Exception:
        log.exception("Erro ao abrir cardápio")
        return redirect(url_for('exibir_mural'))


@app.route('/')
def exibir_mural():
    limpar_expirados()
    notificacoes = 0
    if current_user.is_authenticated:
        try:
            resp_notif = (supabase.table("interesse").select("id", count="exact")
                          .eq("vendedor_id", current_user.id).eq("lido", False).execute())
            notificacoes = resp_notif.count if resp_notif.count else 0
        except Exception:
            log.exception("Erro ao buscar notificações")

    termo = sanitizar_termo_busca(request.args.get('q', ''))
    cat = request.args.get('categoria', '').strip()[:40]
    cidade = request.args.get('cidade', '').strip()[:40]

    cidades_ms = list(CIDADES_MS)
    lojas_food = []

    try:
        query = supabase.table("pedido").select("*, autor:usuario(*)")
        if termo:
            query = query.or_(f"titulo.ilike.%{termo}%,categoria.ilike.%{termo}%")
        if cat:
            query = query.eq("categoria", cat)
        if cidade:
            query = query.eq("local", cidade)

        resp = query.order("plano", desc=True).execute()
        dados_pedidos = resp.data if resp.data else []

        if cat == 'Food':
            resp_food = supabase.table("categorias").select("*").execute()
            lojas_food = resp_food.data if resp_food.data else []

        pedidos_obj = []
        anuncios_afiliados = []

        for p in dados_pedidos:
            obj_pedido = Pedido(**{k: v for k, v in p.items() if k != 'autor'})
            if p.get('autor'):
                obj_pedido.autor = criar_usuario_publico(p['autor'])
            if getattr(obj_pedido, 'is_afiliado', False) or obj_pedido.categoria == 'Achadinhos':
                anuncios_afiliados.append(obj_pedido)
            else:
                pedidos_obj.append(obj_pedido)

        agrupados_por_plano = {}
        for p in pedidos_obj:
            agrupados_por_plano.setdefault(p.plano or 0, []).append(p)

        pedidos_normais = []
        for plano in sorted(agrupados_por_plano.keys(), reverse=True):
            lista = agrupados_por_plano[plano]
            random.shuffle(lista)
            pedidos_normais.extend(lista)

        random.shuffle(anuncios_afiliados)

        # Achadinhos relâmpago (premium) vão para o topo
        achadinhos_premium = [p for p in anuncios_afiliados if p.is_premium or p.plano == 2]
        achadinhos_comuns = [p for p in anuncios_afiliados if not (p.is_premium or p.plano == 2)]

        if current_user.is_authenticated:
            meus_normais = [p for p in pedidos_normais if p.usuario_id == current_user.id]
            outros_normais = [p for p in pedidos_normais if p.usuario_id != current_user.id]
            meus_achadinhos = [p for p in achadinhos_comuns if p.usuario_id == current_user.id]
            outros_achadinhos = [p for p in achadinhos_comuns if p.usuario_id != current_user.id]
            pedidos = achadinhos_premium + meus_normais + outros_normais + meus_achadinhos + outros_achadinhos
        else:
            pedidos = achadinhos_premium + pedidos_normais + achadinhos_comuns

    except Exception:
        log.exception("Erro na busca do mural")
        pedidos = []

    return render_template('mural.html', pedidos=pedidos, lojas_food=lojas_food, busca_ativa=termo,
                           cat_ativa=cat, cidade_ativa=cidade, cidades_ms=cidades_ms,
                           notificacoes=notificacoes)


@app.route('/sugestoes_busca')
def sugestoes_busca():
    query = sanitizar_termo_busca(request.args.get('q', '').lower())
    if len(query) < 2:
        return jsonify([])
    if excedeu_limite(f"sugestao:{ip_cliente()}", 60, 60):
        return jsonify([]), 429
    try:
        resp = supabase.table("pedido").select("titulo").ilike("titulo", f"%{query}%").limit(5).execute()
        return jsonify([p['titulo'] for p in resp.data] if resp.data else [])
    except Exception:
        log.exception("Erro nas sugestões de busca")
        return jsonify([])


@app.route('/cadastrar')
@login_required
def pagina_cadastro():
    return render_template('cadastro.html', cidades_ms=list(CIDADES_MS))


@app.route('/salvar_pedido', methods=['POST'])
@login_required
def salvar_pedido():
    if excedeu_limite(f"novo-anuncio:{current_user.id}", 20, 3600):
        flash("Você publicou muitos anúncios em pouco tempo. Tente novamente mais tarde.")
        return redirect(url_for('pagina_cadastro'))

    dados_validos, erro = validar_dados_anuncio(request.form)
    if erro:
        flash(erro)
        return redirect(url_for('pagina_cadastro'))

    preco_f = converter_preco_br(request.form.get('preco', ''))

    try:
        plano_escolhido = int(request.form.get('plano', 0))
    except (TypeError, ValueError):
        plano_escolhido = 0
    if plano_escolhido not in (0, 1, 2):
        plano_escolhido = 0

    nomes = ['sem-foto.jpg', '', '']
    salvas = []
    try:
        for i, campo in enumerate(['foto', 'foto2', 'foto3']):
            arq = request.files.get(campo)
            if arq and arq.filename:
                nome = salvar_imagem(arq, prefixo=f"foto{i + 1}")
                nomes[i] = nome
                salvas.append(nome)
    except ValueError:
        for n in salvas:
            remover_arquivo_upload(n)
        flash("Uma das fotos não é uma imagem válida (use JPG, PNG, WEBP ou GIF).")
        return redirect(url_for('pagina_cadastro'))

    try:
        agora = datetime.now(fuso_ivinhema)
        vencimento = agora + timedelta(days=365)
        dados_pedido = {
            **dados_validos,
            "whatsapp": current_user.whatsapp,
            "foto": nomes[0],
            "foto2": nomes[1],
            "foto3": nomes[2],
            "data_criacao": agora.isoformat(),
            "data_expiracao": vencimento.isoformat(),
            "plano": 0,
            "plano_aguardando": plano_escolhido,
            "is_premium": False,
            "preco": preco_f,
            "usuario_id": current_user.id
        }
        supabase.table("pedido").insert(dados_pedido).execute()
        return redirect(url_for('exibir_mural'))
    except Exception:
        log.exception("Erro ao salvar no Supabase")
        for n in salvas:
            remover_arquivo_upload(n)
        flash("Erro ao salvar o anúncio. Tente novamente.")
        return redirect(url_for('pagina_cadastro'))


@app.route('/editar_pedido/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_pedido(id):
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    if not resp.data:
        abort(404)
    pedido = Pedido(**resp.data[0])
    if pedido.usuario_id != current_user.id:
        return redirect(url_for('exibir_mural'))

    if request.method == 'POST':
        dados_validos, erro = validar_dados_anuncio(request.form, categoria_atual=pedido.categoria)
        if erro:
            flash(erro)
            return redirect(url_for('editar_pedido', id=id))

        novas = {}
        antigas_para_remover = []
        try:
            for campo, indice in (('foto', 1), ('foto2', 2), ('foto3', 3)):
                arq = request.files.get(campo)
                antiga = getattr(pedido, campo)
                if arq and arq.filename:
                    nova = salvar_imagem(arq, prefixo=f"foto{indice}")
                    novas[campo] = nova
                    antigas_para_remover.append(antiga)
                else:
                    novas[campo] = antiga
        except ValueError:
            for campo in ('foto', 'foto2', 'foto3'):
                if campo in novas and novas[campo] != getattr(pedido, campo):
                    remover_arquivo_upload(novas[campo])
            flash("Uma das fotos não é uma imagem válida (use JPG, PNG, WEBP ou GIF).")
            return redirect(url_for('editar_pedido', id=id))

        try:
            supabase.table("pedido").update({**dados_validos, **novas}).eq("id", id).execute()
        except Exception:
            log.exception("Erro ao atualizar anúncio no Supabase")
            for campo in ('foto', 'foto2', 'foto3'):
                if novas.get(campo) != getattr(pedido, campo):
                    remover_arquivo_upload(novas[campo])
            flash("Erro ao salvar as alterações.")
            return redirect(url_for('exibir_mural'))

        for antiga in antigas_para_remover:
            remover_arquivo_upload(antiga)
        return redirect(url_for('exibir_mural'))

    return render_template('cadastro.html', pedido_edit=pedido, i=pedido, cidades_ms=list(CIDADES_MS))


# ============================================================
# AÇÕES E API
# ============================================================
@app.route('/denunciar_anuncio/<int:id>')
@exige_origem
def denunciar_anuncio(id):
    if not current_user.is_authenticated:
        return jsonify({"status": "erro", "mensagem": "Faça login para denunciar."}), 401
    # Cada usuário denuncia um anúncio só 1x por dia (não conta duplicado)
    if excedeu_limite(f"den:{current_user.id}:{id}", 1, 86400):
        return jsonify({"status": "sucesso"})
    if excedeu_limite(f"den-user:{current_user.id}", 20, 3600):
        return jsonify({"status": "erro", "mensagem": "Muitas denúncias em pouco tempo."}), 429
    try:
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        if not resp.data:
            return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
        p = resp.data[0]
        if p.get('verificado'):
            return jsonify({"status": "imune"})
        novas_denuncias = (p.get('denuncias') or 0) + 1
        dados_update = {"denuncias": novas_denuncias}
        if novas_denuncias >= 3:
            dados_update["is_premium"] = False
            dados_update["plano"] = 0
        supabase.table("pedido").update(dados_update).eq("id", id).execute()
        return jsonify({"status": "sucesso"})
    except Exception:
        log.exception("Erro ao processar denúncia")
        return jsonify({"status": "erro"}), 500


@app.route('/contar_clique_imagem/<int:id>')
@exige_origem
def contar_clique_imagem(id):
    # 1 clique contado por IP/anúncio a cada 10 minutos
    if excedeu_limite(f"clique:{ip_cliente()}:{id}", 1, 600):
        return jsonify({"status": "sucesso"})
    try:
        resp = supabase.table("pedido").select("acessos").eq("id", id).execute()
        if not resp.data:
            return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
        acessos_atualizados = (resp.data[0].get('acessos') or 0) + 1
        supabase.table("pedido").update({"acessos": acessos_atualizados}).eq("id", id).execute()
        return jsonify({"status": "sucesso"})
    except Exception:
        log.exception("Erro ao contar clique")
        return jsonify({"status": "erro"}), 500


@app.route('/registrar_venda/<string:categoria>')
@exige_origem
def registrar_venda(categoria):
    if not re.fullmatch(r'[\w \-]{1,40}', categoria):
        return jsonify({"status": "erro", "mensagem": "Categoria inválida"}), 400
    if excedeu_limite(f"venda:{ip_cliente()}", 30, 3600):
        return jsonify({"status": "erro"}), 429
    try:
        supabase.table("venda_estatistica").insert({"categoria": categoria}).execute()
        return jsonify({"status": "sucesso"})
    except Exception:
        log.exception("Erro ao registrar estatística")
        return jsonify({"status": "erro"}), 500


@app.route('/registrar_interesse/<int:anuncio_id>')
@login_required
@exige_origem
def registrar_interesse(anuncio_id):
    if excedeu_limite(f"interesse:{current_user.id}", 60, 3600):
        return jsonify({"status": "erro", "mensagem": "Muitas solicitações. Tente mais tarde."}), 429
    try:
        resp_anuncio = supabase.table("pedido").select("*").eq("id", anuncio_id).execute()
        if not resp_anuncio.data:
            return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado."}), 404
        anuncio = resp_anuncio.data[0]
        if anuncio['usuario_id'] == current_user.id:
            return jsonify({"status": "erro", "mensagem": "Você não pode demonstrar interesse no seu próprio anúncio!"})
        resp_existente = (supabase.table("interesse").select("*")
                          .eq("anuncio_id", anuncio_id).eq("comprador_id", current_user.id).execute())
        if not resp_existente.data:
            supabase.table("interesse").insert({
                "anuncio_id": anuncio_id,
                "comprador_id": current_user.id,
                "vendedor_id": anuncio['usuario_id']
            }).execute()
            return jsonify({"status": "sucesso", "mensagem": "Solicitação enviada ao vendedor!"})
        return jsonify({"status": "ja_enviado", "mensagem": "Você já demonstrou interesse neste item."})
    except Exception:
        log.exception("Erro ao registrar interesse")
        return jsonify({"status": "erro", "mensagem": "Erro técnico ao processar solicitação."}), 500


# ============================================================
# PERFIL E LOGIN
# ============================================================
@app.route('/completar_perfil', methods=['GET', 'POST'])
@login_required
def completar_perfil():
    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        bairro = (request.form.get('bairro') or '').strip()
        bio = (request.form.get('bio') or '').strip()
        whatsapp = "".join(filter(str.isdigit, request.form.get('whatsapp', '')))
        instagram = request.form.get('instagram', '').replace('@', '').strip()

        erro = None
        if not nome or len(nome) > 80:
            erro = "Informe um nome de até 80 caracteres."
        elif len(bairro) > 60:
            erro = "Bairro muito longo."
        elif len(bio) > 300:
            erro = "A bio pode ter no máximo 300 caracteres."
        elif len(whatsapp) > 15:
            erro = "WhatsApp inválido."
        elif instagram and not re.fullmatch(r'[A-Za-z0-9._]{1,30}', instagram):
            erro = "Instagram inválido (use só letras, números, ponto e underline)."

        if erro:
            flash(erro)
        else:
            dados_update = {"nome": nome, "bairro": bairro, "bio": bio,
                            "whatsapp": whatsapp, "instagram": instagram}
            foto_antiga = None
            try:
                file = request.files.get('foto')
                if file and file.filename:
                    nova_foto = salvar_imagem(file, tamanho=(300, 300), subpasta='perfil',
                                              prefixo=f"perfil_{current_user.id}")
                    foto_antiga = current_user.foto_perfil
                    dados_update["foto_perfil"] = nova_foto
                supabase.table("usuario").update(dados_update).eq("id", current_user.id).execute()
                for chave, valor in dados_update.items():
                    setattr(current_user, chave, valor)
                if foto_antiga:
                    remover_arquivo_upload(foto_antiga)
                flash("Perfil atualizado com sucesso!")
                return redirect(url_for('exibir_mural'))
            except ValueError:
                flash("A foto não é uma imagem válida (use JPG, PNG, WEBP ou GIF).")
            except Exception:
                log.exception("Erro ao salvar perfil")
                if dados_update.get("foto_perfil"):
                    remover_arquivo_upload(dados_update["foto_perfil"])
                flash("Erro ao salvar as alterações.")

    try:
        agora = datetime.now(fuso_ivinhema)
        meu_id_numero = int(current_user.id)
        resp_meus = supabase.table("pedido").select("*").eq("usuario_id", meu_id_numero).execute()
        dados_pedidos = resp_meus.data if resp_meus.data else []
        meus_anuncios = []
        for p in dados_pedidos:
            try:
                obj_pedido = Pedido(**p)
                if not hasattr(obj_pedido, 'data_expiracao') or obj_pedido.data_expiracao is None:
                    data_inicio = getattr(obj_pedido, 'data_postagem', agora)
                    obj_pedido.data_expiracao = data_inicio + timedelta(days=30)
                meus_anuncios.append(obj_pedido)
            except Exception:
                log.exception("Erro ao montar o anúncio ID %s", p.get('id'))
    except Exception:
        log.exception("Erro GERAL ao buscar os anúncios do perfil")
        meus_anuncios = []
        agora = datetime.now(fuso_ivinhema)
    return render_template('completar_perfil.html', meus_anuncios=meus_anuncios, hoje=agora)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_inf = (request.form.get('email') or '').lower().strip()[:254]
        senha_inf = (request.form.get('senha') or '')[:128]
        ip = ip_cliente()

        if (excedeu_limite(f"login-ip:{ip}", 15, 600, registrar=False) or
                excedeu_limite(f"login-email:{email_inf}", 5, 600, registrar=False)):
            flash("Muitas tentativas. Aguarde alguns minutos e tente de novo.")
            return render_template('login.html'), 429

        try:
            resp = supabase.table("usuario").select("*").eq("email", email_inf).execute()
            senha_ok = False
            user = None
            if resp.data:
                user = Usuario(**resp.data[0])
                senha_ok = bool(user.senha) and check_password_hash(user.senha, senha_inf)
            else:
                check_password_hash(_HASH_FALSO, senha_inf)  # iguala o tempo de resposta

            if senha_ok:
                login_user(user, remember=True)
                return redirect(url_for('exibir_mural'))

            excedeu_limite(f"login-ip:{ip}", 15, 600)
            excedeu_limite(f"login-email:{email_inf}", 5, 600)
            flash("E-mail ou senha incorretos.")
        except Exception:
            log.exception("Erro ao realizar login")
            flash("Erro técnico ao tentar logar. Tente novamente.")
    return render_template('login.html')


@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    if request.method == 'POST':
        if excedeu_limite(f"cadastro:{ip_cliente()}", 10, 3600):
            flash("Muitos cadastros deste endereço. Tente novamente mais tarde.", "erro")
            return redirect(url_for('cadastro_usuario'))

        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').lower().strip()
        senha = request.form.get('senha') or ''

        if not nome or len(nome) > 80:
            flash("Informe um nome de até 80 caracteres.", "erro")
            return redirect(url_for('cadastro_usuario'))
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            flash("E-mail inválido.", "erro")
            return redirect(url_for('cadastro_usuario'))
        if len(senha) < 8:
            flash("A senha precisa de pelo menos 8 dígitos!", "erro")
            return redirect(url_for('cadastro_usuario'))
        if len(senha) > 128:
            flash("A senha pode ter no máximo 128 caracteres.", "erro")
            return redirect(url_for('cadastro_usuario'))

        senha_com_hash = generate_password_hash(senha)
        try:
            dados_usuario = {
                "nome": nome,
                "email": email,
                "senha": senha_com_hash,
                "foto_perfil": "default_perfil.png",
                "bairro": "Ivinhema",
                "bio": "Vendedor verificado no Marketplace Ivinhema",
                "data_cadastro": datetime.now(fuso_ivinhema).isoformat()
            }
            resp = supabase.table("usuario").insert(dados_usuario).execute()
            if resp.data:
                novo = dict(resp.data[0])
                novo.pop('senha', None)
                login_user(Usuario(**novo), remember=True)
                return redirect(url_for('completar_perfil'))
        except Exception:
            log.exception("Erro no cadastro via Supabase")
            flash("Erro ao realizar cadastro. Verifique se este e-mail já está cadastrado.", "erro")
            return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html')


# ============================================================
# ADMIN
# ============================================================
@app.route('/admin_mural')
@somente_admin
def admin_mural():
    limpar_expirados()
    try:
        resp_food = supabase.table("categorias").select("*").eq("aprovado", False).order("id", desc=True).execute()
        parceiros_pendentes = resp_food.data if resp_food.data else []
        resp_pedidos = supabase.table("pedido").select("*, autor:usuario(*)").order("id", desc=True).execute()
        pedidos_dados = resp_pedidos.data if resp_pedidos.data else []
        todos = [Pedido(**{k: v for k, v in p.items() if k != 'autor'}) for p in pedidos_dados]
        for obj, bruto in zip(todos, pedidos_dados):
            if bruto.get('autor'):
                obj.autor = criar_usuario_publico(bruto['autor'], manter_email=True)

        resp_vendas = supabase.table("venda_estatistica").select("*").execute()
        vendas_lista = resp_vendas.data if resp_vendas.data else []
        total_vendas_realizadas = len(vendas_lista)
        contagem = {}
        for v in vendas_lista:
            cat = v.get('categoria') or 'Sem Categoria'
            contagem[cat] = contagem.get(cat, 0) + 1
        stats_categorias = list(contagem.items())

        resp_top = supabase.table("pedido").select("*").order("acessos", desc=True).limit(5).execute()
        mais_acessados = [Pedido(**p) for p in resp_top.data] if resp_top.data else []
        top_1 = mais_acessados[0] if mais_acessados else None

        faturamento = sum(15 if (p.plano or 0) == 2 else 5 for p in todos if p.is_premium and (p.plano or 0) > 0)
        total_den = sum(1 for p in todos if (p.denuncias or 0) > 0)
        pendentes_cont = sum(1 for p in todos if (p.plano_aguardando or 0) > 0 and (p.plano or 0) == 0)

        pedidos_normais = [p for p in todos if p.categoria != 'Achadinhos']
        pedidos_achadinhos = [p for p in todos if p.categoria == 'Achadinhos']
        todos_organizados = pedidos_normais + pedidos_achadinhos

        return render_template('admin.html', pedidos=todos_organizados, faturamento=faturamento,
                               total_denuncias=total_den, total_vendas=total_vendas_realizadas,
                               stats_categorias=stats_categorias, mais_acessados=mais_acessados,
                               top_1=top_1, ultimos=todos[:5], pendentes=pendentes_cont,
                               parceiros_food=parceiros_pendentes)
    except Exception:
        log.exception("Erro no painel admin")
        return "Erro ao carregar o painel administrativo."


@app.route('/admin/aprovar_loja/<int:loja_id>')
@somente_admin
@exige_origem
def admin_aprovar_loja(loja_id):
    try:
        supabase.table("categorias").update({"aprovado": True}).eq("id", loja_id).execute()
        return redirect(url_for('admin_mural'))
    except Exception:
        log.exception("Erro ao aprovar parceiro")
        return "Erro ao processar a aprovação."


@app.route('/admin/rejeitar_loja/<int:loja_id>')
@somente_admin
@exige_origem
def admin_rejeitar_loja(loja_id):
    try:
        supabase.table("categorias").delete().eq("id", loja_id).execute()
        return redirect(url_for('admin_mural'))
    except Exception:
        log.exception("Erro ao deletar parceiro")
        return "Erro ao processar a exclusão do parceiro."


@app.route('/tornar_premium/<int:id>')
@somente_admin
@exige_origem
def tornar_premium(id):
    try:
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        if not resp.data:
            abort(404)
        p = Pedido(**resp.data[0])
        agora = datetime.now(fuso_ivinhema)
        nova_expiracao = agora + timedelta(days=30)
        if (p.plano or 0) == 0 and (p.plano_aguardando or 0) > 0:
            dados_update = {
                "plano": 2,
                "is_premium": True,
                "plano_aguardando": 0,
                "data_criacao": agora.isoformat(),
                "data_expiracao": nova_expiracao.isoformat()
            }
        else:
            novo_status = not p.is_premium
            dados_update = {"is_premium": novo_status, "plano": 2 if novo_status else 0}
        supabase.table("pedido").update(dados_update).eq("id", id).execute()
    except HTTPException:
        raise
    except Exception:
        log.exception("Erro ao alterar status premium")
        flash("Erro ao processar a alteração do plano.")
    return redirect(url_for('admin_mural'))


@app.route('/impulsionar_ouro/<int:id>')
@somente_admin
@exige_origem
def impulsionar_ouro(id):
    agora = datetime.now(fuso_ivinhema)
    nova_expiracao = agora + timedelta(days=30)
    try:
        supabase.table("pedido").update({
            "plano": 2,
            "is_premium": True,
            "data_criacao": agora.isoformat(),
            "data_expiracao": nova_expiracao.isoformat(),
            "plano_aguardando": 0
        }).eq("id", id).execute()
        flash("Anúncio impulsionado para OURO! Já está no topo do mural.", "success")
    except Exception:
        log.exception("Erro ao impulsionar")
        flash("Erro técnico ao impulsionar anúncio.")
    return redirect(url_for('admin_mural'))


@app.route('/solicitar_turbo/<int:id>')
@login_required
@exige_origem
def solicitar_turbo(id):
    try:
        resp = supabase.table("pedido").select("id").eq("id", id).eq("usuario_id", current_user.id).execute()
        if not resp.data:
            flash("Anúncio não encontrado.")
            return redirect(url_for('completar_perfil'))
        supabase.table("pedido").update({"plano_aguardando": 2}).eq("id", id).execute()
        flash("Pedido de Turbo enviado! Assim que o PIX for confirmado, você volta ao topo.")
    except Exception:
        log.exception("Erro ao solicitar turbo")
    return redirect(url_for('completar_perfil'))


@app.route('/limpar_denuncias/<int:id>')
@somente_admin
@exige_origem
def limpar_denuncias(id):
    try:
        resp = supabase.table("pedido").select("id").eq("id", id).execute()
        if not resp.data:
            abort(404)
        supabase.table("pedido").update({"denuncias": 0, "verificado": True}).eq("id", id).execute()
    except HTTPException:
        raise
    except Exception:
        log.exception("Erro ao limpar denúncias")
        flash("Não foi possível limpar as denúncias agora.")
    return redirect(url_for('admin_mural'))


@app.route('/excluir_pedido/<int:id>')
@login_required
@exige_origem
def excluir_pedido(id):
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    if not resp.data:
        abort(404)
    p = Pedido(**resp.data[0])

    e_dono = (p.usuario_id == current_user.id)
    e_admin = admin_autenticado()

    if not (e_dono or e_admin):
        log.warning("Exclusão negada: user=%s anuncio=%s dono=%s", current_user.id, id, p.usuario_id)
        return "Sem permissão.", 403

    try:
        supabase.table("interesse").delete().eq("anuncio_id", id).execute()
        for f in (p.foto, p.foto2, p.foto3):
            remover_arquivo_upload(f)
        supabase.table("pedido").delete().eq("id", id).execute()
        return redirect(url_for('exibir_mural'))
    except Exception:
        log.exception("Erro ao excluir no Supabase")
        return "Erro ao excluir o anúncio.", 500


@app.route('/zerar_estatisticas')
@somente_admin
@exige_origem
def zerar_estatisticas():
    try:
        supabase.table("pedido").update({"acessos": 0}).gt("id", 0).execute()
    except Exception:
        log.exception("Erro ao zerar estatísticas")
    return redirect(url_for('admin_mural'))


@app.route('/limpar_inativos_manual')
@somente_admin
@exige_origem
def limpar_inativos_manual():
    try:
        prazo = datetime.now(timezone.utc) - timedelta(days=180)
        resp = supabase.table("usuario").select("id").lt("ultimo_acesso", prazo.isoformat()).execute()
        inativos = [u for u in (resp.data or []) if u['id'] != current_user.id]
        for u in inativos:
            supabase.table("usuario").delete().eq("id", u['id']).execute()
        flash(f"✅ Limpeza concluída! {len(inativos)} contas inativas (6 meses+) foram removidas.")
    except Exception:
        log.exception("Erro na limpeza manual")
        flash("❌ Erro na limpeza. Veja os logs do servidor.")
    return redirect(url_for('admin_mural'))


# ============================================================
# UTILITÁRIOS E MISC
# ============================================================
@app.route('/instalar')
def pagina_instalar():
    return render_template('instalar.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('exibir_mural'))


@app.route('/anuncio/<int:id>', defaults={'slug': ''})
@app.route('/anuncio/<int:id>/<string:slug>')
def ver_anuncio_unico(id, slug=""):
    try:
        resp = supabase.table("pedido").select("*, autor:usuario(*)").eq("id", id).execute()
        if not resp.data:
            abort(404)
        dados = resp.data[0]
        if 'eu ia' in dados:
            dados['id'] = dados['eu ia']
        if 'preço' in dados:
            dados['preco'] = dados['preço']
        elif 'price' in dados:
            dados['preco'] = dados['price']

        autor_bruto = dados.pop('autor', None)
        p_real = Pedido(**dados)
        if autor_bruto:
            p_real.autor = criar_usuario_publico(autor_bruto)
        else:
            p_real.autor = Usuario(nome="Vendedor", instagram="")

        class AnuncioFake:
            def __init__(self, original):
                self.id = getattr(original, 'id', getattr(original, 'eu_ia', None))
                self.titulo = original.titulo
                self.categoria = original.categoria
                self.descricao = original.descricao
                self.whatsapp = original.whatsapp
                self.local = original.local
                self.foto = getattr(original, 'foto', getattr(original, 'imagem', getattr(original, 'photo', '')))
                self.foto2 = getattr(original, 'foto2', None)
                self.foto3 = getattr(original, 'foto3', None)
                self.preco = getattr(original, 'preco', getattr(original, 'preço', getattr(original, 'price', 0.0)))
                self.usuario_id = original.usuario_id
                self.autor = original.autor
                self.instagram = original.autor.instagram
                bruto_data = getattr(original, 'data_criacao', getattr(original, 'data_postagem', None))
                if isinstance(bruto_data, str):
                    try:
                        limpo_data = bruto_data.split('.')[0].replace('Z', '')
                        self.data_postagem = datetime.strptime(limpo_data, "%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        try:
                            self.data_postagem = datetime.strptime(bruto_data.split(' ')[0], "%Y-%m-%d")
                        except Exception:
                            self.data_postagem = datetime.now()
                else:
                    self.data_postagem = bruto_data if bruto_data else datetime.now()
                self.denuncias = 0
                self.verificado = True
                self.is_premium = True
                self.plano = 2

        anuncio_para_exibir = AnuncioFake(p_real)
        return render_template('mural.html', pedidos=[anuncio_para_exibir], pedido=anuncio_para_exibir,
                               busca_ativa='', cat_ativa='')
    except HTTPException:
        raise
    except Exception:
        log.exception("Erro crítico na rota do anúncio único")
        return redirect(url_for('exibir_mural'))


def _numero(valor):
    try:
        return float(valor) if valor else 0
    except (TypeError, ValueError):
        return 0


@app.route('/api/anuncios_extras')
def anuncios_extras():
    anuncio_id = request.args.get('id', type=int)
    categoria = (request.args.get('categoria') or '').strip()[:40]
    if anuncio_id is None:
        return jsonify({'do_vendedor': [], 'relacionados': []}), 400
    try:
        resp_atual = supabase.table("pedido").select("usuario_id").eq("id", anuncio_id).execute()
        if not resp_atual.data:
            return jsonify({'do_vendedor': [], 'relacionados': []})
        vendedor = resp_atual.data[0]['usuario_id']

        colunas = "id,titulo,preco,foto"
        do_vendedor = (supabase.table("pedido").select(colunas).eq("usuario_id", vendedor)
                       .neq("id", anuncio_id).limit(20).execute().data or [])
        relacionados = (supabase.table("pedido").select(colunas).eq("categoria", categoria)
                        .neq("id", anuncio_id).neq("usuario_id", vendedor).limit(20).execute().data or [])

        def fmt(p):
            return {'id': p.get('id', 0), 'titulo': p.get('titulo', ''),
                    'preco': _numero(p.get('preco')), 'foto': p.get('foto', '')}

        return jsonify({'do_vendedor': [fmt(p) for p in do_vendedor],
                        'relacionados': [fmt(p) for p in relacionados]})
    except Exception:
        log.exception("Erro na API de anúncios extras")
        return jsonify({'do_vendedor': [], 'relacionados': []}), 500


@app.route('/.well-known/assetlinks.json')
def servir_assetlinks():
    return app.send_static_file('assetlinks.json'), 200, {'Content-Type': 'application/json'}


@app.route('/recuperar_senha', methods=['GET', 'POST'])
def recuperar_senha():
    # ATENÇÃO: supabase.auth NÃO altera a senha da sua tabela "usuario" própria.
    # Para recuperação de senha de verdade é preciso gerar token + enviar e-mail por conta própria.
    if request.method == 'POST':
        if excedeu_limite(f"recuperar:{ip_cliente()}", 5, 3600):
            flash("Muitas tentativas. Tente novamente mais tarde.")
            return render_template('recuperar_senha.html'), 429
        email = (request.form.get('email') or '').strip().lower()[:254]
        if EMAIL_RE.fullmatch(email):
            try:
                supabase.auth.reset_password_email(email)
            except Exception:
                log.exception("Erro ao enviar e-mail de recuperação")
        # Mesma resposta exista ou não a conta (não revela e-mails cadastrados)
        flash("Se o e-mail estiver cadastrado, você receberá as instruções.")
    return render_template('recuperar_senha.html')


@app.route('/api/extrair_dados', methods=['POST'])
@somente_admin
def extrair_dados():
    dados = request.get_json(silent=True) or {}
    url = url_http_segura(dados.get('url'))
    if not url:
        return jsonify({'erro': 'URL inválida.'}), 400
    if excedeu_limite(f"extrair:{ip_cliente()}", 30, 600):
        return jsonify({'erro': 'Muitas consultas. Aguarde um pouco.'}), 429
    try:
        html = buscar_html_seguro(url)
        soup = BeautifulSoup(html, 'html.parser')
        meta_titulo = soup.find("meta", property="og:title")
        meta_img = soup.find("meta", property="og:image")
        titulo = None
        if meta_titulo and meta_titulo.get('content'):
            titulo = meta_titulo['content']
        elif soup.title and soup.title.string:
            titulo = soup.title.string.strip()
        foto = url_http_segura(meta_img.get('content')) if meta_img else ''
        return jsonify({'titulo': (titulo or 'Título não encontrado')[:200], 'foto': foto})
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception:
        log.exception("Erro ao extrair dados da URL")
        return jsonify({'erro': 'Não foi possível ler essa página.'}), 502


@app.route('/cadastrar_achadinho', methods=['POST'])
@somente_admin
def cadastrar_achadinho():
    titulo = (request.form.get('titulo') or '').strip()
    if not titulo or len(titulo) > 200:
        flash("Título inválido (até 200 caracteres).")
        return redirect(url_for('admin_mural'))

    link_afiliado = url_http_segura(request.form.get('link_afiliado'))
    if not link_afiliado:
        flash("Link de afiliado inválido: use um endereço http:// ou https://")
        return redirect(url_for('admin_mural'))

    foto_url = url_http_segura(request.form.get('foto_url'))
    plataforma = (request.form.get('plataforma') or '').strip()[:40]

    is_promo = request.form.get('is_promo') == 'sim'
    try:
        dias_promo = min(max(int(request.form.get('dias_promo', 7)), 1), 30)
    except (TypeError, ValueError):
        dias_promo = 7

    agora_utc = datetime.now(timezone.utc)
    vencimento = agora_utc + timedelta(days=dias_promo if is_promo else 365)

    dados = {
        "titulo": titulo,
        "preco": converter_preco_simples(request.form.get('preco', 0)),
        "foto": foto_url,
        "link_afiliado": link_afiliado,
        "plataforma": plataforma,
        "is_afiliado": True,
        "categoria": "Achadinhos",
        "usuario_id": current_user.id,
        "plano": 2 if is_promo else 0,
        "is_premium": is_promo,
        "data_criacao": agora_utc.isoformat(),
        "data_expiracao": vencimento.isoformat()
    }

    try:
        supabase.table("pedido").insert(dados).execute()
        return redirect(url_for('admin_mural'))
    except Exception:
        log.exception("Erro ao cadastrar achadinho")
        flash("Erro ao cadastrar o achadinho. Veja os logs do servidor.")
        return redirect(url_for('admin_mural'))


if __name__ == '__main__':
    app.run(host=os.environ.get('HOST', '127.0.0.1'),
            port=int(os.environ.get('PORT', '5000')),
            debug=_env_bool("FLASK_DEBUG"))
