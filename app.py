from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_from_directory, after_this_request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_moment import Moment 
from datetime import datetime, timedelta, timezone
import os, time
from werkzeug.utils import secure_filename
from functools import wraps
from PIL import Image, ImageOps
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
import shutil
from supabase import create_client, Client
import random
import hashlib
import requests
from bs4 import BeautifulSoup


def eh_o_vitor_logado():
    if current_user.is_authenticated:
        email_atual = current_user.email.lower().strip()
        hash_atual = hashlib.sha256(email_atual.encode('utf-8')).hexdigest()
        HASH_DO_VITOR = "62cb801d6d053699405774827ee01e8a2d6de446f05fdc61861004b09dff7923"
        return hash_atual == HASH_DO_VITOR
    return False

app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-muito-segura'

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)



app.config['BABEL_DEFAULT_LOCALE'] = 'pt_br'
moment = Moment(app)
fuso_ivinhema = timezone(timedelta(hours=-4))

HASH_NOME = "scrypt:32768:8:1$0xB1zv3iVa46Cg6C$868d6addcff26950eace72985b1ff46081b4c7dfe37ee8aa38a6b0f5414140317b64ee5c128d624fe2a16e1bb72fab592e57c0c3ed989be4d21770fa559a42e2" 
HASH_SENHA = "scrypt:32768:8:1$7TMwbLFwWdtt1xIv$22f775be96a6a22227b4c64d30f5e7b17c0805c028e657702ea8a28cf85ff8a043b06d5dbe89902780c0845f7f8dae1b82d77a69953b13b64be3f82042ccb7e7"

def precisa_de_senha(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (check_password_hash(HASH_NOME, auth.username) and check_password_hash(HASH_SENHA, auth.password)):
            return Response('Acesso negado!', 401, {'WWW-Authenticate': 'Basic realm="Login"'})
        return f(*args, **kwargs)
    return decorated

if os.path.exists('/data'):
    BASE_DIR = '/data'
    app.config['UPLOAD_FOLDER'] = '/data/uploads'
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')

app.config['IMAGENS_SISTEMA'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static') 

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

def salvar_foto(arq, index=0):
    if arq and arq.filename != '':
        ext = os.path.splitext(arq.filename)[1].lower()
        nome_foto = f"foto_{int(time.time())}_{index}{ext}"
        caminho = os.path.join(app.config['UPLOAD_FOLDER'], nome_foto)
        
        img = Image.open(arq)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            print(f"Erro ao corrigir orientação: {e}")

        if img.mode in ("RGBA", "P"): 
            img = img.convert("RGB")
            
        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        img.save(caminho, optimize=True, quality=85)
        
        return nome_foto
    return None

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

def limpar_expirados():
    hoje = datetime.now(fuso_ivinhema)
    try:
        resp = supabase.table("pedido").select("id, data_expiracao, foto, foto2, foto3").execute()
        pedidos_nuvem = resp.data if resp.data else []
        vencidos = []
        for p in pedidos_nuvem:
            try:
                exp_str = p.get('data_expiracao', '').replace('T', ' ')[:19] 
                if not exp_str: continue
                data_vencimento = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                data_vencimento = fuso_ivinhema.localize(data_vencimento)
            except Exception: continue
            if hoje > data_vencimento:
                vencidos.append(p)
        for p in vencidos:
            for f in [p.get('foto'), p.get('foto2'), p.get('foto3')]:
                if f and f != 'sem-foto.jpg':
                    caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                    if os.path.exists(caminho): 
                        try: os.remove(caminho)
                        except: pass
            supabase.table("pedido").delete().eq("id", p['id']).execute()
    except Exception as e:
        print(f"Erro ao limpar expirados: {e}")

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "faça o login para acessar esta página."
login_manager.login_message_category = "msg-alerta"

@login_manager.user_loader
def load_user(user_id):
    try:
        resp = supabase.table("usuario").select("*").eq("id", int(user_id)).execute()
        if resp.data:
            return Usuario(**resp.data[0])
    except Exception as e:
        print(f"Erro ao carregar sessão do usuário: {e}")
    return None

@app.route('/cardapio_loja/<int:id_loja>')
def ver_cardapio_loja(id_loja):
    try:
        resp_loja = supabase.table("categorias").select("*").eq("id", id_loja).single().execute()
        loja_dados = resp_loja.data
        resp_itens = supabase.table("item_cardapio").select("*").eq("lanchonete_id", id_loja).execute()
        itens_dados = resp_itens.data if resp_itens.data else []
        return render_template('cardapio.html', lanchonete=loja_dados, itens=itens_dados)
    except Exception as e:
        print(f"Erro ao abrir cardápio: {e}")
        return redirect(url_for('index'))

@app.route('/')
def exibir_mural():
    limpar_expirados()
    notificacoes = 0
    if current_user.is_authenticated:
        try:
            resp_notif = supabase.table("interesse").select("id", count="exact").eq("vendedor_id", current_user.id).eq("lido", False).execute()
            notificacoes = resp_notif.count if resp_notif.count else 0
        except Exception as e:
            print(f"Erro ao buscar notificações: {e}")
    
    termo = request.args.get('q', '').strip()
    cat = request.args.get('categoria', '').strip() 
    cidade = request.args.get('cidade', '').strip() 

    cidades_ms = ['Ivinhema', 'Angélica', 'Novo Horizonte', 'Deodápolis', 'Dourados', 'Naviraí', 'Nova Andradina']
    cidades_ms.sort() 
    lojas_food = []
    
    try:
        query = supabase.table("pedido").select("*, autor:usuario(*)")
        if termo: query = query.or_(f"titulo.ilike.%{termo}%,categoria.ilike.%{termo}%")
        if cat: query = query.eq("categoria", cat)
        if cidade: query = query.eq("local", cidade)
            
        resp = query.order("plano", desc=True).execute()
        dados_pedidos = resp.data if resp.data else []
        
        if cat == 'Food':
            resp_food = supabase.table("categorias").select("*").execute()
            lojas_food = resp_food.data if resp_food.data else []

        pedidos_obj = []
        anuncios_afiliados = [] 

        for p in dados_pedidos:
            obj_pedido = Pedido(**p)
            if p.get('autor'):
                obj_pedido.autor = Usuario(**p['autor'])
            
            if getattr(obj_pedido, 'is_afiliado', False) or obj_pedido.categoria == 'Achadinhos':
                anuncios_afiliados.append(obj_pedido)
            else:
                pedidos_obj.append(obj_pedido)
        
        agrupados_por_plano = {}
        for p in pedidos_obj:
            plano = p.plano
            if plano not in agrupados_por_plano: agrupados_por_plano[plano] = []
            agrupados_por_plano[plano].append(p)
            
        pedidos_normais = []
        for plano in sorted(agrupados_por_plano.keys(), reverse=True):
            lista = agrupados_por_plano[plano]
            random.shuffle(lista)
            pedidos_normais.extend(lista)

        random.shuffle(anuncios_afiliados)

        # === LÓGICA DE ORDENAÇÃO FINAL (Prioridade do usuário + Achadinhos no final) ===
        if current_user.is_authenticated:
            # Separamos os MEUS anúncios dos OUTROS, mantendo a categoria original
            meus_normais = [p for p in pedidos_normais if p.usuario_id == current_user.id]
            outros_normais = [p for p in pedidos_normais if p.usuario_id != current_user.id]
            
            meus_achadinhos = [p for p in anuncios_afiliados if p.usuario_id == current_user.id]
            outros_achadinhos = [p for p in anuncios_afiliados if p.usuario_id != current_user.id]
            
            # Ordem final: Meus normais > Outros normais > Meus Achadinhos > Outros Achadinhos
            pedidos = meus_normais + outros_normais + meus_achadinhos + outros_achadinhos
        else:
            # Se não estiver logado, segue a ordem natural: Normais > Achadinhos
            pedidos = pedidos_normais + anuncios_afiliados

    except Exception as e:
        print(f"Erro na busca do mural: {e}")
        pedidos = []
        
    return render_template('mural.html', pedidos=pedidos, lojas_food=lojas_food, busca_ativa=termo, cat_ativa=cat, cidade_ativa=cidade, cidades_ms=cidades_ms, notificacoes=notificacoes)

@app.route('/sugestoes_busca')
def sugestoes_busca():
    query = request.args.get('q', '').lower()
    if len(query) < 2: return jsonify([])
    try:
        resp = supabase.table("pedido").select("titulo").ilike("titulo", f"%{query}%").limit(5).execute()
        sugestoes = [p['titulo'] for p in resp.data] if resp.data else []
        return jsonify(sugestoes)
    except Exception as e:
        print(f"Erro nas sugestões de busca: {e}")
        return jsonify([])

@app.route('/cadastrar')
@login_required
def pagina_cadastro():
    cidades_ms = ['Ivinhema', 'Dourados', 'Naviraí', 'Nova Andradina', 'Angélica', 'Novo Horizonte', 'Deodápolis']
    cidades_ms.sort()
    return render_template('cadastro.html', cidades_ms=cidades_ms)

@app.route('/salvar_pedido', methods=['POST'])
@login_required
def salvar_pedido():
    PROIBIDAS = ['caralho', 'porra', 'merda', 'essa puta', 'vigarista', 'golpe', 'urubu do pix', 'ladrão', 'admin', 'lula', 'Bolsonaro']
    titulo = request.form.get('titulo', '').lower()
    desc = request.form.get('descricao', '').lower()
    for p in PROIBIDAS:
        if p in titulo or p in desc:
            flash(f"⚠️ O termo '{p}' não é permitido.")
            return redirect(url_for('pagina_cadastro'))

    valor_in = request.form.get('preco', '').strip()
    try:
        limpo = valor_in.replace('R$', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
        preco_f = float(limpo) if limpo else 0.0
    except: preco_f = 0.0

    nomes = ['sem-foto.jpg', '', '']
    campos = ['foto', 'foto2', 'foto3']
    for i, campo in enumerate(campos):
        if campo in request.files:
            arq = request.files[campo]
            if arq and arq.filename != '':
                ext = os.path.splitext(arq.filename)[1].lower()
                nome_foto = f"foto_{int(time.time())}_{i+1}{ext}"
                caminho = os.path.join(app.config['UPLOAD_FOLDER'], nome_foto)
                img = Image.open(arq)
                if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                img.save(caminho, optimize=True, quality=85)
                nomes[i] = nome_foto

    try:
            plano_escolhido = int(request.form.get('plano', 0))
            agora = datetime.now(fuso_ivinhema)
            vencimento = agora + timedelta(days=365)
            dados_pedido = {
                "titulo": request.form.get('titulo'),
                "categoria": request.form.get('categoria'),
                "descricao": request.form.get('descricao'),
                "whatsapp": current_user.whatsapp, 
                "local": request.form.get('local'),
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
    except Exception as e:
        print(f"Erro ao salvar no Supabase: {e}")
        flash("Erro ao salvar o anúncio. Tente novamente.")
        return redirect(url_for('pagina_cadastro'))

@app.route('/editar_pedido/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_pedido(id):
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    if not resp.data: abort(404)
    p_dados = resp.data[0]
    pedido = Pedido(**p_dados)
    if pedido.usuario_id != current_user.id: return redirect(url_for('exibir_mural'))
    
    if request.method == 'POST':
        pedido.titulo = request.form.get('titulo')
        pedido.categoria = request.form.get('categoria')
        pedido.descricao = request.form.get('descricao')
        pedido.local = request.form.get('local')

        def atualizar_foto_com_limpeza(campo_arquivo, nome_foto_antiga, index):
            arq = request.files.get(campo_arquivo)
            if arq and arq.filename != '':
                if nome_foto_antiga and nome_foto_antiga != 'sem-foto.jpg':
                    caminho_antigo = os.path.join(app.config['UPLOAD_FOLDER'], nome_foto_antiga)
                    if os.path.exists(caminho_antigo):
                        try: os.remove(caminho_antigo)
                        except Exception as e: print(f"Erro ao deletar foto antiga: {e}")
                return salvar_foto(arq, index)
            return nome_foto_antiga

        pedido.foto = atualizar_foto_com_limpeza('foto', pedido.foto, 1)
        pedido.foto2 = atualizar_foto_com_limpeza('foto2', pedido.foto2, 2)
        pedido.foto3 = atualizar_foto_com_limpeza('foto3', pedido.foto3, 3)

        try:
            supabase.table("pedido").update({
                "titulo": pedido.titulo,
                "categoria": pedido.categoria,
                "descricao": pedido.descricao,
                "local": pedido.local,
                "foto": pedido.foto,
                "foto2": pedido.foto2,
                "foto3": pedido.foto3
            }).eq("id", id).execute()
        except Exception as e:
            print(f"Erro ao atualizar anúncio no Supabase: {e}")
            flash("Erro ao salvar as alterações.")
            return redirect(url_for('exibir_mural'))
        return redirect(url_for('exibir_mural'))
    
    cidades_ms = ['Ivinhema', 'Angélica', 'Novo Horizonte', 'Deodápolis', 'Dourados', 'Naviraí', 'Nova Andradina']
    cidades_ms.sort()
    return render_template('cadastro.html', pedido_edit=pedido, i=pedido, cidades_ms=cidades_ms)

@app.route('/denunciar_anuncio/<int:id>')
def denunciar_anuncio(id):
    try:
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        if not resp.data: return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
        p = resp.data[0]
        if p.get('verificado'): return jsonify({"status": "imune"})
        novas_denuncias = (p.get('denuncias') or 0) + 1
        dados_update = {"denuncias": novas_denuncias}
        if novas_denuncias >= 3:
            dados_update["is_premium"] = False
            dados_update["plano"] = 0
        supabase.table("pedido").update(dados_update).eq("id", id).execute()
        return jsonify({"status": "sucesso"})
    except Exception as e:
        print(f"Erro ao processar denúncia no Supabase: {e}")
        return jsonify({"status": "erro"}), 500

@app.route('/contar_clique_imagem/<int:id>')
def contar_clique_imagem(id):
    try:
        resp = supabase.table("pedido").select("acessos").eq("id", id).execute()
        if not resp.data: return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
        p = resp.data[0]
        acessos_atualizados = (p.get('acessos') or 0) + 1
        supabase.table("pedido").update({"acessos": acessos_atualizados}).eq("id", id).execute()
        return jsonify({"status": "sucesso"})
    except Exception as e:
        print(f"Erro ao contar clique no Supabase: {e}")
        return jsonify({"status": "erro"}), 500

@app.route('/registrar_venda/<string:categoria>')
def registrar_venda(categoria):
    try:
        dados_venda = {"categoria": categoria}
        supabase.table("venda_estatistica").insert(dados_venda).execute()
        return jsonify({"status": "sucesso"})
    except Exception as e:
        print(f"Erro ao registrar estatística no Supabase: {e}")
        return jsonify({"status": "erro"}), 500

@app.route('/registrar_interesse/<int:anuncio_id>')
@login_required
def registrar_interesse(anuncio_id):
    try:
        resp_anuncio = supabase.table("pedido").select("*").eq("id", anuncio_id).execute()
        if not resp_anuncio.data: abort(404)
        anuncio = resp_anuncio.data[0]
        if anuncio['usuario_id'] == current_user.id:
            return jsonify({"status": "erro", "mensagem": "Você não pode demonstrar interesse no seu próprio anúncio!"})
        resp_existente = supabase.table("interesse").select("*").eq("anuncio_id", anuncio_id).eq("comprador_id", current_user.id).execute()
        if not resp_existente.data:
            novo_interesse_dados = {
                "anuncio_id": anuncio_id,
                "comprador_id": current_user.id,
                "vendedor_id": anuncio['usuario_id']
            }
            supabase.table("interesse").insert(novo_interesse_dados).execute()
            return jsonify({"status": "sucesso", "mensagem": "Solicitação enviada ao vendedor!"})
        return jsonify({"status": "ja_enviado", "mensagem": "Você já demonstrou interesse neste item."})
    except Exception as e:
        print(f"Erro ao registrar interesse no Supabase: {e}")
        return jsonify({"status": "erro", "mensagem": "Erro técnico ao processar solicitação."}), 500

@app.route('/completar_perfil', methods=['GET', 'POST'])
@login_required
def completar_perfil():
    if request.method == 'POST':
        nome = request.form.get('nome')
        bairro = request.form.get('bairro')
        bio = request.form.get('bio')
        zap_bruto = request.form.get('whatsapp', '')
        whatsapp = "".join(filter(str.isdigit, zap_bruto))
        insta_bruto = request.form.get('instagram', '')
        instagram = insta_bruto.replace('@', '').strip()
        dados_update = {"nome": nome, "bairro": bairro, "bio": bio, "whatsapp": whatsapp, "instagram": instagram}
        file = request.files.get('foto')
        if file and file.filename != '':
            foto_antiga = current_user.foto_perfil
            if foto_antiga and foto_antiga != 'default_perfil.png':
                caminho_antigo = os.path.join(app.config['UPLOAD_FOLDER'], foto_antiga)
                if os.path.exists(caminho_antigo):
                    try: os.remove(caminho_antigo)
                    except: pass
            ext = os.path.splitext(file.filename)[1].lower()
            nome_foto = f"perfil_{current_user.id}_{int(time.time())}{ext}"
            pasta_perfil = os.path.join(app.config['UPLOAD_FOLDER'], 'perfil')
            if not os.path.exists(pasta_perfil): os.makedirs(pasta_perfil)
            caminho = os.path.join(pasta_perfil, nome_foto)
            img = Image.open(file)
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except: pass
            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            img.save(caminho, optimize=True, quality=85)
            dados_update["foto_perfil"] = f"perfil/{nome_foto}"
        try:
            supabase.table("usuario").update(dados_update).eq("id", current_user.id).execute()
            for chave, valor in dados_update.items(): setattr(current_user, chave, valor)
            flash("Perfil updated com sucesso!")
            return redirect(url_for('exibir_mural'))
        except Exception as e:
            print(f"Erro ao salvar perfil: {e}")
            flash("Erro ao salvar as alterações.")
    
    try:
        try: agora = datetime.now(fuso_ivinhema)
        except: agora = datetime.now()
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
            except Exception as err:
                print(f"Erro ao montar o anúncio ID {p.get('id')}: {err}")
    except Exception as e:
        print(f"Erro GERAL ao buscar os anúncios do perfil: {e}")
        meus_anuncios = []
        agora = datetime.now()
    return render_template('completar_perfil.html', meus_anuncios=meus_anuncios, hoje=agora)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_inf = request.form.get('email', '').lower().strip()
        senha_inf = request.form.get('senha')
        try:
            resp = supabase.table("usuario").select("*").eq("email", email_inf).execute()
            if resp.data:
                dados_usuario = resp.data[0]
                user = Usuario(**dados_usuario)
                if check_password_hash(user.senha, senha_inf):
                    login_user(user)
                    return redirect(url_for('exibir_mural'))
            flash("E-mail ou senha incorretos.")
        except Exception as e:
            print(f"Erro ao realizar login no Supabase: {e}")
            flash("Erro técnico ao tentar logar. Tente novamente.")
    return render_template('login.html')

@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').lower().strip()
        senha = request.form.get('senha')
        if len(senha) < 8:
            flash("A senha precisa de pelo menos 8 dígitos!", "erro")
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
                novo_usuario = Usuario(**resp.data[0])
                login_user(novo_usuario)
                return redirect(url_for('completar_perfil'))
        except Exception as e:
            print(f"Erro no cadastro via Supabase: {e}")
            flash("Erro ao realizar cadastro. Verifique se este e-mail já está cadastrado.", "erro")
            return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html')

@app.route('/admin_mural')
@precisa_de_senha
def admin_mural():
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    limpar_expirados()
    try:
        resp_food = supabase.table("categorias").select("*").eq("aprovado", False).order("id", desc=True).execute()
        parceiros_pendentes = resp_food.data if resp_food.data else []
        resp_pedidos = supabase.table("pedido").select("*, autor:usuario(*)").order("id", desc=True).execute()
        pedidos_dados = resp_pedidos.data if resp_pedidos.data else []
        todos = [Pedido(**p) for p in pedidos_dados]
        resp_vendas = supabase.table("venda_estatistica").select("*").execute()
        vendas_lista = resp_vendas.data if resp_vendas.data else []
        total_vendas_realizadas = len(vendas_lista)
        contagem = {}
        for v in vendas_lista:
            cat = v.get('categoria', 'Sem Categoria')
            contagem[cat] = contagem.get(cat, 0) + 1
        stats_categorias = list(contagem.items())
        resp_top = supabase.table("pedido").select("*").order("acessos", desc=True).limit(5).execute()
        mais_acessados = [Pedido(**p) for p in resp_top.data] if resp_top.data else []
        top_1 = mais_acessados[0] if mais_acessados else None
        faturamento = sum(15 if p.plano == 2 else 5 for p in todos if p.is_premium and p.plano > 0)
        total_den = sum(1 for p in todos if (p.denuncias or 0) > 0)
        pendentes_cont = sum(1 for p in todos if p.plano_aguardando > 0 and p.plano == 0)

        # === INÍCIO DA LÓGICA ADICIONADA: JOGAR ACHADINHOS PRO FINAL ===
        pedidos_normais = []
        pedidos_achadinhos = []
        for p in todos:
            if p.categoria == 'Achadinhos':
                pedidos_achadinhos.append(p)
            else:
                pedidos_normais.append(p)
        
        todos_organizados = pedidos_normais + pedidos_achadinhos
        
        return render_template('admin.html', pedidos=todos_organizados, faturamento=faturamento, total_denuncias=total_den, total_vendas=total_vendas_realizadas, stats_categorias=stats_categorias, mais_acessados=mais_acessados, top_1=top_1, ultimos=todos[:5], pendentes=pendentes_cont, parceiros_food=parceiros_pendentes)
    
    except Exception as e:
        print(f"Erro no painel admin: {e}")
        return "Erro ao carregar o painel administrativo."

@app.route('/admin/aprovar_loja/<int:loja_id>')
def admin_aprovar_loja(loja_id):
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        supabase.table("categorias").update({"aprovado": True}).eq("id", loja_id).execute()
        return redirect(url_for('admin_mural'))
    except Exception as e:
        print(f"Erro ao aprovar parceiro: {e}")
        return "Erro ao processar a aprovação."

@app.route('/tornar_premium/<int:id>')
@precisa_de_senha
def tornar_premium(id):
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        if not resp.data: abort(404)
        p_dados = resp.data[0]
        p = Pedido(**p_dados)
        agora = datetime.now(fuso_ivinhema)
        nova_expiracao = agora + timedelta(days=30)
        dados_update = {}
        if p.plano == 0 and p.plano_aguardando > 0:
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
    except Exception as e:
        print(f"Erro ao alterar status premium no Supabase: {e}")
        flash("Erro ao processar a alteração do plano.")
    return redirect(url_for('admin_mural'))

@app.route('/impulsionar_ouro/<int:id>')
@precisa_de_senha
def impulsionar_ouro(id):
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
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
    except Exception as e:
        print(f"Erro ao impulsionar: {e}")
        flash("Erro técnico ao impulsionar anúncio.")
    return redirect(url_for('admin_mural'))

@app.route('/solicitar_turbo/<int:id>')
@login_required
def solicitar_turbo(id):
    try:
        resp = supabase.table("pedido").select("id").eq("id", id).eq("usuario_id", current_user.id).execute()
        if not resp.data:
            flash("Anúncio não encontrado.")
            return redirect(url_for('completar_perfil'))
        supabase.table("pedido").update({"plano_aguardando": 2}).eq("id", id).execute()
        flash("Pedido de Turbo enviado! Assim que o PIX for confirmado, você volta ao topo.")
    except Exception as e:
        print(f"Erro ao solicitar turbo: {e}")
    return redirect(url_for('completar_perfil'))

@app.route('/limpar_denuncias/<int:id>')
@precisa_de_senha
def limpar_denuncias(id):
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        resp = supabase.table("pedido").select("id").eq("id", id).execute()
        if not resp.data: abort(404)
        supabase.table("pedido").update({"denuncias": 0, "verificado": True}).eq("id", id).execute()
    except Exception as e:
        print(f"Erro ao limpar denúncias no Supabase: {e}")
        flash("Não foi possível limpar as denúncias agora.")
    return redirect(url_for('admin_mural'))

@app.route('/excluir_pedido/<int:id>')
@login_required
def excluir_pedido(id):
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    if not resp.data: abort(404)
    p_dados = resp.data[0]
    p = Pedido(**p_dados)
    
    # Verificação de permissão melhorada com log de debug
    e_dono = (p.usuario_id == current_user.id)
    e_admin = getattr(current_user, 'is_admin', False)
    
    if e_dono or e_admin:
        try:
            # 1. Remove interesses vinculados
            supabase.table("interesse").delete().eq("anuncio_id", id).execute()
            
            # 2. Remove fotos físicas
            for f in [p.foto, p.foto2, p.foto3]:
                if f and f != 'sem-foto.jpg' and f != '':
                    caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                    if os.path.exists(caminho):
                        try: os.remove(caminho)
                        except Exception as e: print(f"Erro ao remover arquivo físico: {e}")
            
            # 3. Exclui o anúncio
            supabase.table("pedido").delete().eq("id", id).execute()
            return redirect(url_for('exibir_mural'))
            
        except Exception as e:
            print(f"Erro ao excluir no Supabase: {e}")
            return f"Erro ao excluir: {e}", 500
    else:
        # LOG DE SEGURANÇA: Isso aparecerá no seu terminal quando der o erro 403
        print(f"DEBUG EXCLUSÃO: Tentativa falha. UserID Logado: {current_user.id}, Anúncio OwnerID: {p.usuario_id}, É Admin: {e_admin}")
        return "Sem permissão. Verifique seu ID de usuário ou status de Admin.", 403

@app.route('/zerar_estatisticas')
@precisa_de_senha
def zerar_estatisticas():
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        supabase.table("venda_estatistica").delete().gt("id", 0).execute()
    except Exception as e:
        print(f"Erro ao zerar estatísticas: {e}")
    return redirect(url_for('admin_mural'))

@app.route('/instalar')
def pagina_instalar():
    return render_template('instalar.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('exibir_mural'))

@app.route('/baixar_banco')
@precisa_de_senha
def baixar_banco():
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        return send_from_directory(directory=BASE_DIR, path='mural.db', as_attachment=True)
    except Exception as e:
        return f"Erro ao baixar banco: {str(e)}"

@app.route('/limpar_inativos_manual')
@precisa_de_senha
def limpar_inativos_manual():
    if not eh_o_vitor_logado(): return redirect(url_for('exibir_mural'))
    try:
        prazo = datetime.now(timezone.utc) - timedelta(days=180)
        prazo_iso = prazo.isoformat()
        resp = supabase.table("usuario").select("id").lt("ultimo_acesso", prazo_iso).execute()
        inativos = resp.data if resp.data else []
        quantidade = len(inativos)
        if quantidade > 0:
            for u in inativos:
                supabase.table("usuario").delete().eq("id", u['id']).execute()
        flash(f"✅ Limpeza concluída! {quantidade} contas inativas (6 meses+) foram removidas.")
    except Exception as e:
        print(f"Erro na limpeza manual: {e}")
        flash(f"❌ Erro na limpeza: {str(e)}")
    return redirect(url_for('admin_mural'))

@app.route('/anuncio/<int:id>', defaults={'slug': ''})
@app.route('/anuncio/<int:id>/<string:slug>')
def ver_anuncio_unico(id, slug=""):
    try:
        resp = supabase.table("pedido").select("*, autor:usuario(*)").eq("id", id).execute()
        if not resp.data: abort(404)
        dados = resp.data[0]
        if 'eu ia' in dados: dados['id'] = dados['eu ia']
        if 'preço' in dados: dados['preco'] = dados['preço']
        elif 'price' in dados: dados['preco'] = dados['price']

        p_real = Pedido(**dados) if isinstance(dados, dict) else Pedido()
        if dados.get('autor'): p_real.autor = Usuario(**dados['autor'])
        else: p_real.autor = Usuario(nome="Vendedor", instagram="")

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
                    except:
                        try: self.data_postagem = datetime.strptime(bruto_data.split(' ')[0], "%Y-%m-%d")
                        except: self.data_postagem = datetime.now()
                else: self.data_postagem = bruto_data if bruto_data else datetime.now()
                self.denuncias = 0  
                self.verificado = True  
                self.is_premium = True  
                self.plano = 2  

        anuncio_para_exibir = AnuncioFake(p_real)
        return render_template('mural.html', pedidos=[anuncio_para_exibir], pedido=anuncio_para_exibir, busca_ativa='', cat_ativa='')
    except Exception as e:
        print(f"Erro crítico na rota do anúncio único: {e}")
        return redirect(url_for('exibir_mural'))

@app.route('/api/anuncios_extras')
def anuncios_extras():
    anuncio_id = request.args.get('id', type=int)
    categoria = request.args.get('categoria')
    try:
        resp_atual = supabase.table("pedido").select("usuario_id").eq("id", anuncio_id).execute()
        if not resp_atual.data: return jsonify({'do_vendedor': [], 'relacionados': []})
        usuario_id_vendedor = resp_atual.data[0]['usuario_id']
        resp_vendedor = supabase.table("pedido").select("*").eq("usuario_id", usuario_id_vendedor).neq("id", anuncio_id).execute()
        do_vendedor = resp_vendedor.data if resp_vendedor.data else []
        resp_relacionados = supabase.table("pedido").select("*").eq("categoria", categoria).neq("id", anuncio_id).neq("usuario_id", usuario_id_vendedor).execute()
        relacionados = resp_relacionados.data if resp_relacionados.data else []
        return jsonify({
            'do_vendedor': [{'id': p.get('id', p.get('eu ia', p.get('eu_ia', 0))), 'titulo': p.get('titulo', ''), 'preco': float(p.get('preco', p.get('preço', p.get('price', 0)))) if (p.get('preco') or p.get('preço') or p.get('price')) else 0, 'foto': p.get('foto', p.get('imagem', p.get('photo', '')))} for p in do_vendedor],
            'relacionados': [{'id': p.get('id', p.get('eu ia', p.get('eu_ia', 0))), 'titulo': p.get('titulo', ''), 'preco': float(p.get('preco', p.get('preço', p.get('price', 0)))) if (p.get('preco') or p.get('preço') or p.get('price')) else 0, 'foto': p.get('foto', p.get('imagem', p.get('photo', '')))} for p in relacionados]
        })
    except Exception as e:
        print(f"Erro na API de anúncios extras: {e}")
        return jsonify({'do_vendedor': [], 'relacionados': []}), 500
        
@app.route('/admin/rejeitar_loja/<int:loja_id>')
def admin_rejeitar_loja(loja_id):
    try:
        supabase.table("categorias").delete().eq("id", loja_id).execute()
        return redirect(url_for('admin_mural'))
    except Exception as e:
        print(f"🚨 Erro ao deletar parceiro: {e}")
        return "Erro ao processar a exclusão do parceiro."

@app.route('/.well-known/assetlinks.json')
def servir_assetlinks():
    return app.send_static_file('assetlinks.json'), 200, {'Content-Type': 'application/json'}

@app.route('/recuperar_senha', methods=['GET', 'POST'])
def recuperar_senha():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            # O Supabase envia o e-mail automaticamente
            supabase.auth.reset_password_email(email)
            flash("Verifique seu e-mail para resetar a senha.")
        except Exception as e:
            flash("Erro ao enviar e-mail. Verifique o endereço.")
    return render_template('recuperar_senha.html')

@app.route('/api/extrair_dados', methods=['POST'])
def extrair_dados():
    url = request.json.get('url')
    try:
        # Adicionamos um User-Agent mais robusto e aceitamos outros formatos
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.google.com/'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Tenta pegar das tags OpenGraph
        titulo = soup.find("meta", property="og:title")
        img = soup.find("meta", property="og:image")
        
        # fallback: tenta pegar a tag <title> padrão se não achar a OpenGraph
        titulo_final = titulo['content'] if titulo else (soup.title.string if soup.title else 'Título não encontrado')
        
        return jsonify({
            'titulo': titulo_final,
            'foto': img['content'] if img else ''
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/cadastrar_achadinho', methods=['POST'])
@login_required # Garante que só usuários logados consigam postar
def cadastrar_achadinho():
    
    dados = {
        "titulo": request.form.get('titulo'),
        "preco": float(request.form.get('preco', 0)),
        "foto": request.form.get('foto_url'),
        "link_afiliado": request.form.get('link_afiliado'),
        "plataforma": request.form.get('plataforma'),
        "is_afiliado": True,
        "categoria": "Achadinhos",
        "usuario_id": 6
    }
    
    # Tenta inserir e imprime o erro se falhar
    try:
        supabase.table("pedido").insert(dados).execute()
        return redirect(url_for('admin_mural'))
    except Exception as e:
        return f"Erro bruto do Supabase: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)