from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_from_directory, after_this_request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_moment import Moment 
from datetime import datetime, timedelta, timezone
import os, time
from werkzeug.utils import secure_filename
from functools import wraps
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
import shutil
from supabase import create_client, Client
import random
from flask import request


app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-muito-segura'


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CONFIGURAÇÃO ---
app.config['BABEL_DEFAULT_LOCALE'] = 'pt_br'
moment = Moment(app)
fuso_ivinhema = timezone(timedelta(hours=-4))

# --- ADMIN ---
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

# --- BANCO DE DADOS ---
# --- CONFIGURAÇÃO DE CAMINHOS (PC vs RAILWAY COM VOLUME) ---
# --- CONFIGURAÇÃO DE CAMINHOS (PC vs RAILWAY COM VOLUME) ---
if os.path.exists('/data'):
    # No Railway: Salva tudo no Volume para não apagar no Deploy
    BASE_DIR = '/data'
    app.config['UPLOAD_FOLDER'] = '/data/uploads'
    # SQLALCHEMY_DATABASE_URI removido daqui (agora é Supabase)
else:
    # No seu PC: Continua salvando na pasta do projeto normal
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
    # SQLALCHEMY_DATABASE_URI removido daqui (agora é Supabase)

app.config['IMAGENS_SISTEMA'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static') 
# SQLALCHEMY_TRACK_MODIFICATIONS removido daqui

# Garante que a pasta de fotos exista (especialmente no Volume novo)
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])





# --- ROTA PARA SERVIR AS FOTOS DO VOLUME ---
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    # Esta rota permite que o HTML acesse as fotos dentro de /data/uploads
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

def salvar_foto(arq, index=0):
    if arq and arq.filename != '':
        ext = os.path.splitext(arq.filename)[1].lower()
        nome_foto = f"foto_{int(time.time())}_{index}{ext}"
        caminho = os.path.join(app.config['UPLOAD_FOLDER'], nome_foto)
        
        img = Image.open(arq)
        
        # --- O SEGREDO ESTÁ AQUI: Corrige a rotação automática ---
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            print(f"Erro ao corrigir orientação: {e}")
        # -------------------------------------------------------

        if img.mode in ("RGBA", "P"): 
            img = img.convert("RGB")
            
        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        img.save(caminho, optimize=True, quality=85)
        
        return nome_foto
    return None

# --- MODELOS (Adaptados para a Nuvem / Supabase) ---
# Transformados em classes normais para manter a sua lógica e o seu HTML intactos,
# sem depender do antigo banco SQLite.

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
        self.pedidos = kwargs.get('pedidos', []) # Relacionamento mantido

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
        self.autor = kwargs.get('autor', None) # Relacionamento com Usuario

class VendaEstatistica:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.categoria = kwargs.get('categoria')
        self.data_venda = kwargs.get('data_venda')

# --- NOVA TABELA DE INTERESSADOS ---
class Interesse:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.anuncio_id = kwargs.get('anuncio_id')
        self.comprador_id = kwargs.get('comprador_id')
        self.vendedor_id = kwargs.get('vendedor_id')
        self.data_solicitacao = kwargs.get('data_solicitacao')
        self.lido = kwargs.get('lido', False) 
        # Relacionamentos mantidos para facilitar pegar os nomes depois
        self.anuncio = kwargs.get('anuncio', None)
        self.comprador = kwargs.get('comprador', None)

# --- LIMPEZA ---
def limpar_expirados():
    hoje = datetime.now(fuso_ivinhema)
    limite_gratis = hoje - timedelta(days=7)
    limite_prata = hoje - timedelta(days=15)
    limite_ouro = hoje - timedelta(days=30)
    
    try:
        # Busca todos os pedidos no Supabase para verificar o vencimento
        resp = supabase.table("pedido").select("id, plano, data_criacao, foto, foto2, foto3").execute()
        pedidos_nuvem = resp.data if resp.data else []

        vencidos = []
        for p in pedidos_nuvem:
            try:
                # Transforma a data do banco (string) de volta em data do Python para comparar
                # O Supabase salva com um "T" no meio, então ajustamos a leitura
                data_str = p.get('data_criacao', '').replace('T', ' ')[:19] 
                data_criacao = datetime.strptime(data_str, '%Y-%m-%d %H:%M:%S')
                data_criacao = fuso_ivinhema.localize(data_criacao)
            except Exception as e:
                continue # Se a data estiver vazia ou com erro, pula o anúncio

            plano = p.get('plano', 0)
            
            # Mantendo a sua mesmíssima lógica de vencimento
            if plano == 2 and data_criacao < limite_ouro:
                vencidos.append(p)
            elif plano == 1 and data_criacao < limite_prata:
                vencidos.append(p)
            elif plano == 0 and data_criacao < limite_gratis:
                vencidos.append(p)

        for p in vencidos:
            # Apaga do HD (Sua lógica mantida 100%)
            for f in [p.get('foto'), p.get('foto2'), p.get('foto3')]:
                if f and f != 'sem-foto.jpg':
                    caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                    if os.path.exists(caminho): 
                        try:
                            os.remove(caminho)
                        except: pass
            
            # Deleta da nuvem
            supabase.table("pedido").delete().eq("id", p['id']).execute()
            
    except Exception as e:
        print(f"Erro ao limpar expirados: {e}")

# with app.app_context(): db.create_all() <-- REMOVIDO (O Supabase já tem as tabelas)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- TRADUÇÃO AQUI ---
login_manager.login_message = "faça o login para acessar esta página."
login_manager.login_message_category = "msg-alerta"

@login_manager.user_loader
def load_user(user_id):
    # Traduzido para buscar o usuário logado na nuvem!
    try:
        resp = supabase.table("usuario").select("*").eq("id", int(user_id)).execute()
        if resp.data:
            # Pega o dicionário da nuvem e joga dentro daquela sua classe Usuario
            return Usuario(**resp.data[0])
    except Exception as e:
        print(f"Erro ao carregar sessão do usuário: {e}")
    return None

@app.route('/cardapio_loja/<int:id_loja>')
def ver_cardapio_loja(id_loja):
    try:
        # 1. Busca os dados da lanchonete na tabela 'categorias'
        # Usamos .single() para pegar o dicionário direto da loja
        resp_loja = supabase.table("categorias").select("*").eq("id", id_loja).single().execute()
        loja_dados = resp_loja.data
        
        # 2. Busca os itens vinculados a essa lanchonete
        # IMPORTANTE: A coluna no seu banco deve ser 'lanchonete_id'
        resp_itens = supabase.table("item_cardapio").select("*").eq("lanchonete_id", id_loja).execute()
        itens_dados = resp_itens.data if resp_itens.data else []
        
        # 3. Envia para o template (ajustado para bater com seu HTML)
        return render_template('cardapio.html', lanchonete=loja_dados, itens=itens_dados)
        
    except Exception as e:
        print(f"Erro ao abrir cardápio: {e}")
        # Se der erro, volta para a rota principal do Marketplace
        return redirect(url_for('index'))

# --- ROTAS ---

@app.route('/')
def exibir_mural():
    # 1. Mantendo sua lógica de manutenção
    limpar_expirados()
    
    notificacoes = 0
    
    # 2. Mantendo sua lógica de notificações do vendedor
    if current_user.is_authenticated:
        try:
            resp_notif = supabase.table("interesse").select("id", count="exact").eq("vendedor_id", current_user.id).eq("lido", False).execute()
            notificacoes = resp_notif.count if resp_notif.count else 0
        except Exception as e:
            print(f"Erro ao buscar notificações: {e}")
    
    # 3. Capturando filtros da URL
    termo = request.args.get('q', '').strip()
    cat = request.args.get('categoria', '').strip() 
    cidade = request.args.get('cidade', '').strip() 

    # 4. Sua lista de cidades do MS
    cidades_ms = [
        'Ivinhema', 'Angélica', 'Novo Horizonte', 'Deodápolis',
        'Dourados', 'Naviraí', 'Nova Andradina',
    ]
    cidades_ms.sort() 
    
    lojas_food = []
    
    try:
        # 5. Busca principal de anúncios (Marketplace)
        query = supabase.table("pedido").select("*, autor:usuario(*)")
        
        if termo: 
            query = query.or_(f"titulo.ilike.%{termo}%,categoria.ilike.%{termo}%")
        if cat: 
            query = query.eq("categoria", cat)
        if cidade: 
            query = query.eq("local", cidade)
            
        resp = query.order("plano", desc=True).execute()
        dados_pedidos = resp.data if resp.data else []
        
        # --- LÓGICA DO FOOD ONLINE (Integrada) ---
        # Se o usuário clicar na categoria 'Food', buscamos as lanchonetes parceiras
        if cat == 'Food':
            resp_food = supabase.table("categorias").select("*").execute()
            lojas_food = resp_food.data if resp_food.data else []
            print(f"SISTEMA: {len(lojas_food)} lanchonetes de Ivinhema carregadas.")
        # ------------------------------------------

        # 6. Transformando em objetos (Pedido/Usuario)
        pedidos_obj = []
        for p in dados_pedidos:
            obj_pedido = Pedido(**p)
            if p.get('autor'):
                obj_pedido.autor = Usuario(**p['autor'])
            pedidos_obj.append(obj_pedido)
        
        # 7. Sua lógica de embaralhar (Sorteio por Plano)
        agrupados_por_plano = {}
        for p in pedidos_obj:
            plano = p.plano
            if plano not in agrupados_por_plano:
                agrupados_por_plano[plano] = []
            agrupados_por_plano[plano].append(p)
            
        pedidos = []
        for plano in sorted(agrupados_por_plano.keys(), reverse=True):
            lista = agrupados_por_plano[plano]
            random.shuffle(lista)
            pedidos.extend(lista)
        # --- AGORA A MÁGICA: PRIORIDADE PARA O MEU ANÚNCIO ---
        if current_user.is_authenticated:
            # Pegamos apenas os anúncios que pertencem a VOCÊ
            meus_anuncios = [p for p in pedidos if p.usuario_id == current_user.id]
            # Pegamos o resto dos anúncios (de todo mundo menos os seus)
            outros_anuncios = [p for p in pedidos if p.usuario_id != current_user.id]
            
            # Recriamos a lista: Seus anúncios primeiro, depois o resto embaralhado
            pedidos = meus_anuncios + outros_anuncios

    except Exception as e:
        print(f"Erro na busca do mural: {e}")
        pedidos = []
        
    # 8. Renderizando o mural com todos os dados
    return render_template('mural.html', 
                            pedidos=pedidos, 
                            lojas_food=lojas_food, # Passa as lanchonetes para o HTML
                            busca_ativa=termo, 
                            cat_ativa=cat, 
                            cidade_ativa=cidade,
                            cidades_ms=cidades_ms,
                            notificacoes=notificacoes)



@app.route('/sugestoes_busca')
def sugestoes_busca():
    query = request.args.get('q', '').lower()
    if len(query) < 2: 
        return jsonify([])
    
    try:
        # Busca no Supabase mantendo sua lógica exata de ilike e limite de 5
        # Selecionamos apenas a coluna 'titulo' para a busca ser mais rápida
        resp = supabase.table("pedido").select("titulo").ilike("titulo", f"%{query}%").limit(5).execute()
        
        # Extrai os títulos da lista de dicionários retornada pela nuvem
        sugestoes = [p['titulo'] for p in resp.data] if resp.data else []
        
        return jsonify(sugestoes)
        
    except Exception as e:
        print(f"Erro nas sugestões de busca: {e}")
        return jsonify([])

@app.route('/cadastrar')
@login_required
def pagina_cadastro():
    # 1. Definimos a lista de cidades que você quer sugerir
    cidades_ms = ['Ivinhema', 'Dourados', 'Naviraí', 'Nova Andradina', 'Angélica', 'Novo Horizonte', 'Deodápolis'] # ... sua lista completa
    cidades_ms.sort() # Deixa em ordem alfabética

    # 2. Passamos a lista para o template
    return render_template('cadastro.html', cidades_ms=cidades_ms)

@app.route('/salvar_pedido', methods=['POST'])
@login_required
def salvar_pedido():
    # 1. Trava de palavras proibidas (Mantido idêntico)
    PROIBIDAS = ['caralho', 'porra', 'merda', 'essa puta', 'vigarista', 'golpe', 'urubu do pix', 'ladrão', 'admin', 'lula', 'Bolsonaro']
    titulo = request.form.get('titulo', '').lower()
    desc = request.form.get('descricao', '').lower()
    for p in PROIBIDAS:
        if p in titulo or p in desc:
            flash(f"⚠️ O termo '{p}' não é permitido.")
            return redirect(url_for('pagina_cadastro'))

    # 2. Limpeza de WhatsApp e Preço (Mantido idêntico)
    valor_in = request.form.get('preco', '').strip()
    try:
        limpo = valor_in.replace('R$', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
        preco_f = float(limpo) if limpo else 0.0
    except: preco_f = 0.0

    # 3. Processamento ÚNICO de Fotos (Mantido idêntico - Salva no seu Volume/HD)
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

    # 4. Salvar no Supabase (Tradução do Banco)
    try:
        plano_escolhido = int(request.form.get('plano', 0))
        
        # Preparamos os dados exatamente como a sua tabela na nuvem espera
        dados_pedido = {
            "titulo": request.form.get('titulo'),
            "categoria": request.form.get('categoria'),
            "descricao": request.form.get('descricao'),
            "whatsapp": current_user.whatsapp, 
            "local": request.form.get('local'),
            "foto": nomes[0], 
            "foto2": nomes[1], 
            "foto3": nomes[2],
            "data_criacao": datetime.now(fuso_ivinhema).isoformat(), # Formato de data para nuvem
            "plano": 0, 
            "plano_aguardando": plano_escolhido, 
            "is_premium": False, 
            "preco": preco_f, 
            "usuario_id": current_user.id
        }
        
        # Inserção no Supabase no lugar do db.session.add/commit
        supabase.table("pedido").insert(dados_pedido).execute()
        
        # Redireciona direto para o mural sem travar (Mantido)
        return redirect(url_for('exibir_mural'))   
        
    except Exception as e:
        print(f"Erro ao salvar no Supabase: {e}")
        # Não precisamos de rollback() aqui, o Supabase cancela a operação se der erro
        flash("Erro ao salvar o anúncio. Tente novamente.")
        return redirect(url_for('pagina_cadastro'))

@app.route('/editar_pedido/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_pedido(id):
    # 1. Busca os dados no Supabase no lugar do Pedido.query
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    
    if not resp.data:
        abort(404) # Se não encontrar o anúncio, retorna erro 404
        
    # Transforma o resultado na nossa classe Pedido para manter compatibilidade com seu HTML
    p_dados = resp.data[0]
    pedido = Pedido(**p_dados)
    
    # 2. Trava de segurança (Sua lógica mantida 100%)
    if pedido.usuario_id != current_user.id:
        return redirect(url_for('exibir_mural'))
    
    if request.method == 'POST':
        # Atualiza as variáveis do objeto com os novos dados do formulário
        pedido.titulo = request.form.get('titulo')
        pedido.categoria = request.form.get('categoria')
        pedido.descricao = request.form.get('descricao')
        pedido.local = request.form.get('local')

        # Sua função interna para limpar a foto antiga e salvar a nova (MANTIDA IDÊNTICA)
        def atualizar_foto_com_limpeza(campo_arquivo, nome_foto_antiga, index):
            arq = request.files.get(campo_arquivo)
            if arq and arq.filename != '':
                # 1. Se existir uma foto antiga que não seja a padrão, apaga do disco
                if nome_foto_antiga and nome_foto_antiga != 'sem-foto.jpg':
                    caminho_antigo = os.path.join(app.config['UPLOAD_FOLDER'], nome_foto_antiga)
                    if os.path.exists(caminho_antigo):
                        try:
                            os.remove(caminho_antigo)
                        except Exception as e:
                            print(f"Erro ao deletar foto antiga: {e}")
                
                # 2. Salva a nova foto usando a sua função salvar_foto do topo
                return salvar_foto(arq, index)
            return nome_foto_antiga # Mantém a antiga se não enviou nada novo

        # Atualiza as 3 fotos chamando sua lógica de limpeza
        pedido.foto = atualizar_foto_com_limpeza('foto', pedido.foto, 1)
        pedido.foto2 = atualizar_foto_com_limpeza('foto2', pedido.foto2, 2)
        pedido.foto3 = atualizar_foto_com_limpeza('foto3', pedido.foto3, 3)

        # 3. Salva as alterações na nuvem no lugar do db.session.commit()
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
    
    # No GET, envia o objeto 'pedido' exatamente como o seu cadastro.html espera
    return render_template('cadastro.html', pedido_edit=pedido, i=pedido)


@app.route('/denunciar_anuncio/<int:id>')
def denunciar_anuncio(id):
    try:
        # 1. Busca os dados atuais do anúncio no Supabase
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        
        if not resp.data:
            return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
            
        p = resp.data[0] # Pegamos o dicionário com os dados

        # 2. Se já foi verificado pelo admin, não aceita mais denúncias (Sua lógica mantida)
        if p.get('verificado'):
            return jsonify({"status": "imune"})
        
        # 3. Incrementa o contador de denúncias
        novas_denuncias = (p.get('denuncias') or 0) + 1
        
        # Prepara os dados para atualização
        dados_update = {"denuncias": novas_denuncias}
        
        # 4. Se bater 3 denúncias, perde o destaque imediatamente (Sua lógica mantida)
        if novas_denuncias >= 3:
            dados_update["is_premium"] = False
            dados_update["plano"] = 0
            
        # 5. Salva na nuvem no lugar do db.session.commit()
        supabase.table("pedido").update(dados_update).eq("id", id).execute()
        
        return jsonify({"status": "sucesso"})
        
    except Exception as e:
        print(f"Erro ao processar denúncia no Supabase: {e}")
        return jsonify({"status": "erro"}), 500

@app.route('/contar_clique_imagem/<int:id>')
def contar_clique_imagem(id):
    try:
        # 1. Busca o valor atual de acessos no Supabase
        # Filtramos pelo ID para garantir que pegamos o anúncio correto
        resp = supabase.table("pedido").select("acessos").eq("id", id).execute()
        
        if not resp.data:
            return jsonify({"status": "erro", "mensagem": "Anúncio não encontrado"}), 404
            
        p = resp.data[0]

        # 2. SUA LÓGICA ORIGINAL (Mantida 100% igual)
        # O 'or 0' previne erros caso o campo esteja nulo no banco
        acessos_atualizados = (p.get('acessos') or 0) + 1
        
        # 3. Salva a nova contagem na nuvem
        supabase.table("pedido").update({"acessos": acessos_atualizados}).eq("id", id).execute()
        
        # 4. Retorno JSON (Idêntico ao original para o seu JavaScript funcionar)
        return jsonify({"status": "sucesso"})
        
    except Exception as e:
        print(f"Erro ao contar clique no Supabase: {e}")
        return jsonify({"status": "erro"}), 500

@app.route('/registrar_venda/<string:categoria>')
def registrar_venda(categoria):
    try:
        # 1. Prepara os dados para a tabela de estatísticas
        # O campo 'data_venda' o Supabase preenche sozinho com o now() que configuramos no SQL
        dados_venda = {
            "categoria": categoria
        }
        
        # 2. Insere na nuvem no lugar do db.session.add/commit
        supabase.table("venda_estatistica").insert(dados_venda).execute()
        
        # 3. Retorno de sucesso (Idêntico ao original)
        return jsonify({"status": "sucesso"})
        
    except Exception as e:
        print(f"Erro ao registrar estatística no Supabase: {e}")
        # Retorno de erro (Idêntico ao original)
        return jsonify({"status": "erro"}), 500

@app.route('/registrar_interesse/<int:anuncio_id>')
@login_required
def registrar_interesse(anuncio_id):
    try:
        # 1. Busca o anúncio no Supabase (Equivalente ao get_or_404)
        resp_anuncio = supabase.table("pedido").select("*").eq("id", anuncio_id).execute()
        
        if not resp_anuncio.data:
            abort(404)
            
        anuncio = resp_anuncio.data[0]
        
        # 2. Impede que o dono do anúncio clique no próprio botão (Sua lógica mantida)
        if anuncio['usuario_id'] == current_user.id:
            return jsonify({"status": "erro", "mensagem": "Você não pode demonstrar interesse no seu próprio anúncio!"})

        # 3. Verifica se o interesse já foi registrado antes
        resp_existente = supabase.table("interesse").select("*").eq("anuncio_id", anuncio_id).eq("comprador_id", current_user.id).execute()

        if not resp_existente.data:
            # 4. Se não existe, cria um novo registro na nuvem
            novo_interesse_dados = {
                "anuncio_id": anuncio_id,
                "comprador_id": current_user.id,
                "vendedor_id": anuncio['usuario_id']
                # O campo 'lido' e 'data_solicitacao' o Supabase preenche sozinho (conforme seu SQL)
            }
            
            supabase.table("interesse").insert(novo_interesse_dados).execute()
            
            return jsonify({"status": "sucesso", "mensagem": "Solicitação enviada ao vendedor!"})
        
        # 5. Se já existir, avisa o usuário (Sua lógica mantida)
        return jsonify({"status": "ja_enviado", "mensagem": "Você já demonstrou interesse neste item."})

    except Exception as e:
        print(f"Erro ao registrar interesse no Supabase: {e}")
        return jsonify({"status": "erro", "mensagem": "Erro técnico ao processar solicitação."}), 500

# --- ROTA PARA COMPLETAR PERFIL (PÓS-LOGIN) ---
@app.route('/completar_perfil', methods=['GET', 'POST'])
@login_required
def completar_perfil():
    if request.method == 'POST':
        # 1. Pegar dados do formulário
        nome = request.form.get('nome')
        bairro = request.form.get('bairro')
        bio = request.form.get('bio')
        
        # --- ADICIONADO APENAS ISSO (Lógica de limpeza mantida) ---
        zap_bruto = request.form.get('whatsapp', '')
        whatsapp = "".join(filter(str.isdigit, zap_bruto))
        
        # --- ADICIONE ESTAS DUAS LINHAS AQUI (Lógica de limpeza mantida) ---
        insta_bruto = request.form.get('instagram', '')
        instagram = insta_bruto.replace('@', '').strip()
        
        # Dicionário com os dados para atualizar na nuvem
        dados_update = {
            "nome": nome,
            "bairro": bairro,
            "bio": bio,
            "whatsapp": whatsapp,
            "instagram": instagram
        }
        
        # 2. Lógica da Foto de Perfil com LIMPEZA (IDÊNTICA À ORIGINAL)
        file = request.files.get('foto')
        if file and file.filename != '':
            # --- INÍCIO DA FAXINA NO HD ---
            foto_antiga = current_user.foto_perfil
            if foto_antiga and foto_antiga != 'default_perfil.png':
                caminho_antigo = os.path.join(app.config['UPLOAD_FOLDER'], foto_antiga)
                if os.path.exists(caminho_antigo):
                    try:
                        os.remove(caminho_antigo)
                    except Exception as e:
                        print(f"Erro ao deletar foto antiga: {e}")
            # --- FIM DA FAXINA ---

            ext = os.path.splitext(file.filename)[1].lower()
            nome_foto = f"perfil_{current_user.id}_{int(time.time())}{ext}"
            
            pasta_perfil = os.path.join(app.config['UPLOAD_FOLDER'], 'perfil')
            if not os.path.exists(pasta_perfil):
                os.makedirs(pasta_perfil)
                
            caminho = os.path.join(pasta_perfil, nome_foto)
            
            img = Image.open(file)
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except: pass

            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            img.save(caminho, optimize=True, quality=85)
            
            # Adiciona o novo caminho da foto ao dicionário de update
            dados_update["foto_perfil"] = f"perfil/{nome_foto}"

        # 3. Salva no Supabase (Equivalente ao db.session.commit)
        try:
            supabase.table("usuario").update(dados_update).eq("id", current_user.id).execute()
            
            # Atualiza o objeto current_user na memória para o site mostrar os novos dados na hora
            for chave, valor in dados_update.items():
                setattr(current_user, chave, valor)

            flash("Perfil atualizado com sucesso!")
            return redirect(url_for('exibir_mural'))
        except Exception as e:
            print(f"Erro ao salvar perfil no Supabase: {e}")
            flash("Erro ao salvar as alterações.")

    # --- GET (Visualização da página) ---
    try:
        # CORREÇÃO TÉCNICA: Garantir que o ID seja Inteiro para o Supabase localizar
        user_id_int = int(current_user.id)

        # BUSCA CORRIGIDA: Adicionamos !interesse_comprador_id_fkey para resolver a ambiguidade no banco
        resp = supabase.table("interesse")\
            .select("*, anuncio:pedido(*), comprador:usuario!interesse_comprador_id_fkey(*)")\
            .eq("vendedor_id", user_id_int)\
            .order("data_solicitacao", desc=True)\
            .execute()

        # Transforma os dados em objetos das nossas classes para manter a compatibilidade com o HTML
        meus_interessados = []
        if resp.data:
            for item in resp.data:
                obj_anuncio = Pedido(**item['anuncio']) if item.get('anuncio') else None
                obj_comprador = Usuario(**item['comprador']) if item.get('comprador') else None
                
                interesse = Interesse(**item)
                interesse.anuncio = obj_anuncio
                interesse.comprador = obj_comprador
                meus_interessados.append(interesse)

            # Marca como lido apenas se houver interessados
            supabase.table("interesse").update({'lido': True}).eq("vendedor_id", user_id_int).eq("lido", False).execute()
        
    except Exception as e:
        print(f"Erro ao carregar interesses no Marketplace Ivinhema: {e}")
        meus_interessados = []
        
    return render_template('completar_perfil.html', interessados=meus_interessados)

# --- ATUALIZE SUA ROTA DE LOGIN PARA ISSO ---
from werkzeug.security import check_password_hash

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 1. Captura e limpa os dados (Lógica mantida 100%)
        email_inf = request.form.get('email', '').lower().strip()
        senha_inf = request.form.get('senha')
        
        try:
            # 2. Busca o usuário no Supabase pelo e-mail
            resp = supabase.table("usuario").select("*").eq("email", email_inf).execute()
            
            # Verifica se encontrou algum resultado
            if resp.data:
                # Transforma o dicionário da nuvem em um objeto da sua classe Usuario
                dados_usuario = resp.data[0]
                user = Usuario(**dados_usuario)
                
                # 3. Validação de senha (Atualizada para comparar o Hash)
                # A função check_password_hash verifica se a senha digitada 
                # bate com o código seguro gravado no banco.
                if check_password_hash(user.senha, senha_inf):
                    login_user(user)
                    return redirect(url_for('exibir_mural'))
            
            # Se chegou aqui, é porque o e-mail não existe ou a senha está errada
            flash("E-mail ou senha incorretos.")
            
        except Exception as e:
            print(f"Erro ao realizar login no Supabase: {e}")
            flash("Erro técnico ao tentar logar. Tente novamente.")

    return render_template('login.html')


@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    if request.method == 'POST':
        # 1. Captura e limpa os dados (Mantendo sua lógica de limpeza)
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').lower().strip()
        senha = request.form.get('senha')
        
        # CAPTURA DE AUDITORIA: IP e Versão dos Termos
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        versao_atual = "1.0-2026"
        
        # 2. Trava de segurança de 8 dígitos (Sua lógica original intacta)
        if len(senha) < 8:
            flash("A senha precisa de pelo menos 8 dígitos!", "erro")
            return redirect(url_for('cadastro_usuario'))
        
        senha_com_hash = generate_password_hash(senha)
        
        try:
            # 3. Prepara os dados para o Supabase incluindo os campos de segurança
            dados_usuario = {
                "nome": nome,
                "email": email,
                "senha": senha_com_hash,
                "aceite_termos_ip": user_ip,
                "aceite_termos_versao": versao_atual
            }
            
            # 4. Insere no Supabase (Substituindo o commit do SQL tradicional)
            resp = supabase.table("usuario").insert(dados_usuario).execute()
            
            
            if resp.data:
                # 5. Converte o retorno em objeto Usuario para o Flask-Login
                # O resp.data[0] já traz o ID e a Data gerados pelo Supabase
                novo_usuario = Usuario(**resp.data[0])
                
                # Realiza o login automático do novo usuário
                login_user(novo_usuario)
                
                # 6. Redireciona para completar o perfil (Sua lógica mantida)
                return redirect(url_for('completar_perfil'))
                
        except Exception as e:
            print(f"Erro no cadastro via Supabase: {e}")
            flash("Erro ao realizar cadastro. Verifique se o e-mail já existe.", "erro")
            return redirect(url_for('cadastro_usuario'))
            
    return render_template('cadastro_usuario.html')

@app.route('/admin_mural')
@precisa_de_senha
def admin_mural():
    limpar_expirados()
    
    try:
        # 1. Busca todos os pedidos para o painel
        resp_pedidos = supabase.table("pedido").select("*").order("id", desc=True).execute()
        pedidos_dados = resp_pedidos.data if resp_pedidos.data else []
        # Transformamos em objetos da classe Pedido para que p.plano e p.is_premium funcionem
        todos = [Pedido(**p) for p in pedidos_dados]

        # 2. Busca estatísticas de vendas
        resp_vendas = supabase.table("venda_estatistica").select("*").execute()
        vendas_lista = resp_vendas.data if resp_vendas.data else []
        total_vendas_realizadas = len(vendas_lista)

        # 3. Recriando o stats_categorias (Group By) no Python para manter sua lógica
        contagem = {}
        for v in vendas_lista:
            cat = v.get('categoria', 'Sem Categoria')
            contagem[cat] = contagem.get(cat, 0) + 1
        # Transforma o dicionário em uma lista de tuplas (categoria, contagem)
        stats_categorias = list(contagem.items())

        # 4. Busca os mais acessados (Sua lógica de Top 5)
        resp_top = supabase.table("pedido").select("*").order("acessos", desc=True).limit(5).execute()
        mais_acessados = [Pedido(**p) for p in resp_top.data] if resp_top.data else []
        top_1 = mais_acessados[0] if mais_acessados else None

        # 5. CÁLCULOS FINANCEIROS E ALERTAS (Sua lógica original mantida 100%)
        # Plano 2 = R$ 15 | Plano 1 = R$ 5
        faturamento = sum(15 if p.plano == 2 else 5 for p in todos if p.is_premium and p.plano > 0)
        
        # Conta anúncios com denúncias
        total_den = sum(1 for p in todos if (p.denuncias or 0) > 0)
        
        # Conta anúncios esperando aprovação de plano (pendentes)
        pendentes_cont = sum(1 for p in todos if p.plano_aguardando > 0 and p.plano == 0)

        return render_template(
            'admin.html', 
            pedidos=todos, 
            faturamento=faturamento, 
            total_denuncias=total_den, 
            total_vendas=total_vendas_realizadas, 
            stats_categorias=stats_categorias, 
            mais_acessados=mais_acessados, 
            top_1=top_1, 
            ultimos=todos[:5], 
            pendentes=pendentes_cont
        )

    except Exception as e:
        print(f"Erro no painel administrativo: {e}")
        return "Erro ao carregar o painel ADM", 500

@app.route('/tornar_premium/<int:id>')
@precisa_de_senha
def tornar_premium(id):
    try:
        # 1. Busca os dados atuais do anúncio no Supabase
        resp = supabase.table("pedido").select("*").eq("id", id).execute()
        
        if not resp.data:
            abort(404)
            
        p_dados = resp.data[0]
        # Usamos nossa classe para facilitar a manipulação dos dados
        p = Pedido(**p_dados)

        # 2. SUA LÓGICA DE APROVAÇÃO (Mantida 100% igual)
        # Se o anúncio for grátis (0) mas tiver um plano na fila de espera
        if p.plano == 0 and p.plano_aguardando > 0:
            p.plano = p.plano_aguardando
            p.is_premium = True
            p.plano_aguardando = 0
        else:
            # Caso contrário, apenas inverte o estado (se era True vira False, e vice-versa)
            p.is_premium = not p.is_premium

        # 3. Salva a atualização na nuvem
        supabase.table("pedido").update({
            "plano": p.plano,
            "is_premium": p.is_premium,
            "plano_aguardando": p.plano_aguardando
        }).eq("id", id).execute()

    except Exception as e:
        print(f"Erro ao alterar status premium no Supabase: {e}")
        flash("Erro ao processar a alteração do plano.")

    # 4. Redireciona de volta para o seu painel (Mantido)
    return redirect(url_for('admin_mural'))

@app.route('/limpar_denuncias/<int:id>')
@precisa_de_senha
def limpar_denuncias(id):
    try:
        # 1. Verifica se o anúncio existe no banco de dados da nuvem
        resp = supabase.table("pedido").select("id").eq("id", id).execute()
        
        if not resp.data:
            # Se não encontrar o anúncio, retorna o erro 404 (Página não encontrada)
            abort(404)

        # 2. SUA LÓGICA DE OURO (Mantida 100% igual)
        # Zera o contador e concede a imunidade permanente (verificado = True)
        supabase.table("pedido").update({
            "denuncias": 0,
            "verificado": True 
        }).eq("id", id).execute()

    except Exception as e:
        print(f"Erro ao limpar denúncias no Supabase: {e}")
        flash("Não foi possível limpar as denúncias agora.")

    # 3. Redireciona para o painel administrativo para você continuar a gestão (Mantido)
    return redirect(url_for('admin_mural'))

@app.route('/excluir_pedido/<int:id>')
@login_required
def excluir_pedido(id):
    # 1. Busca o anúncio no Supabase para pegar os nomes das fotos e o dono
    resp = supabase.table("pedido").select("*").eq("id", id).execute()
    
    if not resp.data:
        abort(404)
        
    p_dados = resp.data[0]
    p = Pedido(**p_dados)

    # Verifica se é o dono ou admin (Lógica mantida 100%)
    if p.usuario_id == current_user.id or getattr(current_user, 'is_admin', False):
        try:
            # 1. Limpa os interesses (O Supabase faz isso via CASCADE, mas mantemos o comando)
            supabase.table("interesse").delete().eq("anuncio_id", id).execute()

            # 2. Apaga as fotos do seu servidor/HD (Lógica de faxina mantida)
            for f in [p.foto, p.foto2, p.foto3]:
                if f and f != 'sem-foto.jpg' and f != '':
                    caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                    if os.path.exists(caminho):
                        try:
                            os.remove(caminho)
                        except Exception as e:
                            print(f"Erro ao remover arquivo físico: {e}")

            # 3. Apaga o pedido na nuvem
            supabase.table("pedido").delete().eq("id", id).execute()
            
            return redirect(url_for('exibir_mural'))

        except Exception as e:
            print(f"Erro ao excluir no Supabase: {e}")
            return f"Erro ao excluir: {e}", 500
    else:
        return "Sem permissão", 403

@app.route('/zerar_estatisticas')
@precisa_de_senha
def zerar_estatisticas():
    try:
        # No Supabase, para apagar tudo, filtramos por IDs maiores que 0
        supabase.table("venda_estatistica").delete().gt("id", 0).execute()
    except Exception as e:
        print(f"Erro ao zerar estatísticas: {e}")
        
    return redirect(url_for('admin_mural'))

@app.route('/instalar')
def pagina_instalar():
    # Rota mantida apenas para exibição do template
    return render_template('instalar.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('exibir_mural'))

# --- ROTAS DE BACKUP (MANTIDAS) ---
@app.route('/baixar_banco')
@precisa_de_senha
def baixar_banco():
    try:
        # IMPORTANTE: Como agora os dados estão no Supabase, 
        # este comando baixa o último arquivo local 'mural.db' que existir no servidor.
        return send_from_directory(directory=BASE_DIR, path='mural.db', as_attachment=True)
    except Exception as e:
        return f"Erro ao baixar banco: {str(e)}"

# --------------------------------------

@app.route('/limpar_inativos_manual')
@precisa_de_senha
def limpar_inativos_manual():
    try:
        # 1. Define o prazo de 6 meses (180 dias) - Mantendo sua lógica exata
        # O timezone.utc garante que a data seja universal para a nuvem
        prazo = datetime.now(timezone.utc) - timedelta(days=180)
        prazo_iso = prazo.isoformat() # Transforma em texto para o Supabase entender
        
        # 2. Busca usuários com último acesso antigo no Supabase
        # .lt significa "Less Than" (menor que), ou seja, datas antes do prazo
        resp = supabase.table("usuario").select("id").lt("ultimo_acesso", prazo_iso).execute()
        inativos = resp.data if resp.data else []
        quantidade = len(inativos)
        
        if quantidade > 0:
            for u in inativos:
                # 3. Remove o usuário pelo ID
                # O banco já vai apagar os anúncios dele automaticamente (ON DELETE CASCADE)
                supabase.table("usuario").delete().eq("id", u['id']).execute()
        
        flash(f"✅ Limpeza concluída! {quantidade} contas inativas (6 meses+) foram removidas.")
        
    except Exception as e:
        print(f"Erro na limpeza manual: {e}")
        flash(f"❌ Erro na limpeza: {str(e)}")
        
    return redirect(url_for('admin_mural'))


@app.route('/anuncio/<int:id>')
def ver_anuncio_unico(id):
    try:
        # 1. Busca o pedido e já traz os dados do autor (relacionamento)
        # O select("*, autor:usuario(*)") faz o papel do 'original.autor' do seu banco antigo
        resp = supabase.table("pedido").select("*, autor:usuario(*)").eq("id", id).execute()
        
        if not resp.data:
            abort(404)
            
        dados = resp.data[0]
        
        # Criamos o objeto original para alimentar sua classe AnuncioFake
        p_real = Pedido(**dados)
        
        # Vinculamos o autor manualmente para manter sua lógica de 'original.autor'
        if dados.get('autor'):
            p_real.autor = Usuario(**dados['autor'])
        else:
            # Caso o autor não exista, criamos um objeto vazio para não quebrar o código
            p_real.autor = Usuario(nome="Vendedor", instagram="")

        # --- SUA LÓGICA ORIGINAL (Mantida 100% igual) ---
        class AnuncioFake:
            def __init__(self, original):
                self.id = original.id
                self.titulo = original.titulo
                self.categoria = original.categoria
                self.descricao = original.descricao
                self.whatsapp = original.whatsapp
                self.local = original.local
                self.foto = original.foto
                self.foto2 = getattr(original, 'foto2', None)
                self.foto3 = getattr(original, 'foto3', None)
                # O modal busca exatamente por 'data_postagem'
                self.data_postagem = getattr(original, 'data_criacao', None) 
                self.preco = original.preco
                self.usuario_id = original.usuario_id
                self.autor = original.autor 
                
                # Pega o instagram direto do objeto autor que vinculamos acima
                self.instagram = original.autor.instagram
                
                # ATRIBUTOS ESSENCIAIS PARA O MURAL NÃO TRAVAR (Sua configuração de exibição):
                self.denuncias = 0  
                self.verificado = True 
                self.is_premium = True 
                self.plano = 2 

        anuncio_para_exibir = AnuncioFake(p_real)
        
        # Retorna a lista com um único item para o mural.html
        return render_template('mural.html', pedidos=[anuncio_para_exibir], busca_ativa='', cat_ativa='')

    except Exception as e:
        print(f"Erro ao visualizar anúncio único: {e}")
        return redirect(url_for('exibir_mural'))

@app.route('/api/anuncios_extras')
def anuncios_extras():
    anuncio_id = request.args.get('id', type=int)
    categoria = request.args.get('categoria')
    
    try:
        # Busca o anúncio atual para saber quem é o dono (Lógica mantida)
        resp_atual = supabase.table("pedido").select("usuario_id").eq("id", anuncio_id).execute()
        
        if not resp_atual.data:
            return jsonify({'do_vendedor': [], 'relacionados': []})

        usuario_id_vendedor = resp_atual.data[0]['usuario_id']

        # 1. Mais anúncios deste vendedor (limitado a 6)
        # .neq() significa "Not Equal" (Diferente de), para não mostrar o anúncio que já está aberto
        resp_vendedor = supabase.table("pedido")\
            .select("id, titulo, preco, foto")\
            .eq("usuario_id", usuario_id_vendedor)\
            .neq("id", anuncio_id)\
            .limit(6).execute()
        
        do_vendedor = resp_vendedor.data if resp_vendedor.data else []

        # 2. Anúncios relacionados (mesma categoria, mas não do mesmo vendedor, limitado a 4)
        resp_relacionados = supabase.table("pedido")\
            .select("id, titulo, preco, foto")\
            .eq("categoria", categoria)\
            .neq("id", anuncio_id)\
            .neq("usuario_id", usuario_id_vendedor)\
            .limit(4).execute()
            
        relacionados = resp_relacionados.data if resp_relacionados.data else []

        # Organiza os dados para enviar para o JavaScript (Sua estrutura de retorno mantida)
        # Organiza os dados para enviar para o JavaScript (Corrigido)
        return jsonify({
            'do_vendedor': [{
                'id': p['id'],
                'titulo': p['titulo'],
                'preco': float(p['preco']) if p['preco'] else 0,
                'foto': p['foto']
            } for p in do_vendedor], # Aqui fechamos com } antes do for
            'relacionados': [{
                'id': p['id'],
                'titulo': p['titulo'],
                'preco': float(p['preco']) if p['preco'] else 0,
                'foto': p['foto']
            } for p in relacionados] # Aqui também fechamos com }
        })
    except Exception as e:
        print(f"Erro na API de anúncios extras: {e}")
        return jsonify({'do_vendedor': [], 'relacionados': []}), 500

# --- INICIALIZAÇÃO DO SERVIDOR ---
if __name__ == '__main__':
    # O debug=True continua aqui para facilitar seus testes no Marketplace
    app.run(debug=True)
