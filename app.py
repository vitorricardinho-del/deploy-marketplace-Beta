from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_from_directory, after_this_request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_moment import Moment 
from datetime import datetime, timedelta, timezone
import os, time
from werkzeug.utils import secure_filename
from functools import wraps
from PIL import Image
from werkzeug.security import check_password_hash
from sqlalchemy import func
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-muito-segura'

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
if os.path.exists('/data'):
    # No Railway: Salva tudo no Volume para não apagar no Deploy
    BASE_DIR = '/data'
    app.config['UPLOAD_FOLDER'] = '/data/uploads'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/mural.db'
else:
    # No seu PC: Continua salvando na pasta do projeto normal
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'mural.db')

app.config['IMAGENS_SISTEMA'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static') 
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Garante que a pasta de fotos exista (especialmente no Volume novo)
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)



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

# --- MODELOS ---
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    foto_perfil = db.Column(db.String(200), default='default_perfil.png')
    bairro = db.Column(db.String(100), default='Ivinhema')
    bio = db.Column(db.String(200), default="Vendedor verificado no Marketplace Ivinhema")
    whatsapp = db.Column(db.String(20))
    instagram = db.Column(db.String(100), nullable=True)
    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    pedidos = db.relationship('Pedido', backref='autor', lazy=True)

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50))
    descricao = db.Column(db.Text)
    whatsapp = db.Column(db.String(20))
    local = db.Column(db.String(100))
    foto = db.Column(db.String(200), default='sem-foto.jpg')
    foto2 = db.Column(db.String(200), default='') 
    foto3 = db.Column(db.String(200), default='')
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(fuso_ivinhema)) 
    plano = db.Column(db.Integer, default=0) 
    plano_aguardando = db.Column(db.Integer, default=0) 
    is_premium = db.Column(db.Boolean, default=False)
    preco = db.Column(db.Numeric(10, 2), nullable=True)     
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    acessos = db.Column(db.Integer, default=0)
    denuncias = db.Column(db.Integer, default=0)
    verificado = db.Column(db.Boolean, default=False)

class VendaEstatistica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50))
    data_venda = db.Column(db.DateTime, default=lambda: datetime.now(fuso_ivinhema))

# --- NOVA TABELA DE INTERESSADOS ---
class Interesse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    anuncio_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=False)
    comprador_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    data_solicitacao = db.Column(db.DateTime, default=lambda: datetime.now(fuso_ivinhema))
    lido = db.Column(db.Boolean, default=False) # Para o vendedor saber o que é novo

    # Relacionamentos para facilitar pegar os nomes depois
    anuncio = db.relationship('Pedido', backref='interessados')
    comprador = db.relationship('Usuario', foreign_keys=[comprador_id], backref='interesses_enviados')

# --- LIMPEZA ---
def limpar_expirados():
    hoje = datetime.now(fuso_ivinhema)
    limite_gratis = hoje - timedelta(days=7)
    limite_prata = hoje - timedelta(days=15)
    limite_ouro = hoje - timedelta(days=30)
    vencidos = Pedido.query.filter(
        ((Pedido.plano == 2) & (Pedido.data_criacao < limite_ouro)) |
        ((Pedido.plano == 1) & (Pedido.data_criacao < limite_prata)) |
        ((Pedido.plano == 0) & (Pedido.data_criacao < limite_gratis))
    ).all()
    for p in vencidos:
        for f in [p.foto, p.foto2, p.foto3]:
            if f and f != 'sem-foto.jpg':
                caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                if os.path.exists(caminho): os.remove(caminho)
        db.session.delete(p)
    db.session.commit()

with app.app_context():
    db.create_all()

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- TRADUÇÃO AQUI ---
login_manager.login_message = "faça o login para acessar esta página."
login_manager.login_message_category = "msg-alerta"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# --- ROTAS ---

@app.route('/')
def exibir_mural():
    limpar_expirados()
    
    notificacoes = 0
    
    if current_user.is_authenticated:
        # Busca na tabela Interesse quantos são para este vendedor e que ele não leu (lido=False)
        notificacoes = Interesse.query.filter_by(vendedor_id=current_user.id, lido=False).count()
    
    termo = request.args.get('q', '').strip()
    cat = request.args.get('categoria', '').strip() 
    query = Pedido.query
    if termo: 
        query = query.filter((Pedido.titulo.ilike(f'%{termo}%')) | (Pedido.categoria.ilike(f'%{termo}%')))
    if cat: 
        query = query.filter(Pedido.categoria == cat)
    pedidos = query.order_by(Pedido.plano.desc(), func.random()).all()
    return render_template('mural.html', pedidos=pedidos, busca_ativa=termo, cat_ativa=cat, notificacoes=notificacoes)



@app.route('/sugestoes_busca')
def sugestoes_busca():
    query = request.args.get('q', '').lower()
    if len(query) < 2: 
        return jsonify([])
    
    # Aqui ele busca no seu banco de dados
    # Certifique-se que o nome 'Pedido' é o mesmo da sua classe do banco
    resultados = Pedido.query.filter(Pedido.titulo.ilike(f'%{query}%')).limit(5).all()
    sugestoes = [p.titulo for p in resultados]
    
    return jsonify(sugestoes)


@app.route('/cadastrar')
@login_required
def pagina_cadastro():
    return render_template('cadastro.html')

@app.route('/salvar_pedido', methods=['POST'])
@login_required
def salvar_pedido():
    # 1. Trava de palavras proibidas
    PROIBIDAS = ['caralho', 'porra', 'merda', 'puta', 'vigarista', 'golpe', 'urubu do pix', 'ladrão', 'admin', 'lula', 'Bolsonaro', 'itapuan']
    titulo = request.form.get('titulo', '').lower()
    desc = request.form.get('descricao', '').lower()
    for p in PROIBIDAS:
        if p in titulo or p in desc:
            flash(f"⚠️ O termo '{p}' não é permitido.")
            return redirect(url_for('pagina_cadastro'))

    # 2. Limpeza de WhatsApp e Preço
    valor_in = request.form.get('preco', '').strip()
    try:
        limpo = valor_in.replace('R$', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
        preco_f = float(limpo) if limpo else 0.0
    except: preco_f = 0.0

    # 3. Processamento ÚNICO de Fotos (Sem duplicar)
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

    # 4. Salvar no Banco e Redirecionar
    try:
        plano_escolhido = int(request.form.get('plano', 0))
        novo = Pedido(
            titulo=request.form.get('titulo'),
            categoria=request.form.get('categoria'),
            descricao=request.form.get('descricao'),
            
            whatsapp=current_user.whatsapp, 
            
            local=request.form.get('local'),
            foto=nomes[0], 
            foto2=nomes[1], 
            foto3=nomes[2],
            data_criacao=datetime.now(fuso_ivinhema),
            plano=0, 
            plano_aguardando=plano_escolhido, 
            is_premium=False, 
            preco=preco_f, 
            usuario_id=current_user.id
        )
        db.session.add(novo)
        db.session.commit()
        
        # Redireciona direto para o mural sem travar
        return redirect(url_for('exibir_mural'))   
    except Exception as e:
        print(f"Erro ao salvar: {e}")
        db.session.rollback()
        flash("Erro ao salvar o anúncio. Tente novamente.")
        return redirect(url_for('pagina_cadastro'))

@app.route('/editar_pedido/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_pedido(id):
    pedido = Pedido.query.get_or_404(id)
    
    if pedido.usuario_id != current_user.id:
        return redirect(url_for('exibir_mural'))
    
    if request.method == 'POST':
        pedido.titulo = request.form.get('titulo')
        pedido.categoria = request.form.get('categoria')
        pedido.descricao = request.form.get('descricao')
        pedido.local = request.form.get('local')

        # Função interna para limpar a foto antiga e salvar a nova
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
                
                # 2. Salva a nova foto usando a função que criamos lá no topo
                return salvar_foto(arq, index)
            return nome_foto_antiga # Mantém a antiga se não enviou nada novo

        # Atualiza as 3 fotos com a limpeza automática
        pedido.foto = atualizar_foto_com_limpeza('foto', pedido.foto, 1)
        pedido.foto2 = atualizar_foto_com_limpeza('foto2', pedido.foto2, 2)
        pedido.foto3 = atualizar_foto_com_limpeza('foto3', pedido.foto3, 3)

        db.session.commit()
        return redirect(url_for('exibir_mural'))
    
    return render_template('cadastro.html', pedido_edit=pedido, i=pedido)

@app.route('/denunciar_anuncio/<int:id>')
def denunciar_anuncio(id):
    p = Pedido.query.get_or_404(id)
    # Se já foi verificado pelo admin, não aceita mais denúncias
    if p.verificado:
        return jsonify({"status": "imune"})
    
    p.denuncias = (p.denuncias or 0) + 1
    
    # Se bater 3 denúncias, perde o destaque imediatamente e aguarda análise
    if p.denuncias >= 3:
        p.is_premium = False
        p.plano = 0
        
    db.session.commit()
    return jsonify({"status": "sucesso"})

@app.route('/contar_clique_imagem/<int:id>')
def contar_clique_imagem(id):
    p = Pedido.query.get_or_404(id)
    p.acessos = (p.acessos or 0) + 1
    db.session.commit()
    return jsonify({"status": "sucesso"})

@app.route('/registrar_venda/<string:categoria>')
def registrar_venda(categoria):
    try:
        nova_venda = VendaEstatistica(categoria=categoria)
        db.session.add(nova_venda)
        db.session.commit()
        return jsonify({"status": "sucesso"})
    except:
        return jsonify({"status": "erro"}), 500

@app.route('/registrar_interesse/<int:anuncio_id>')
@login_required
def registrar_interesse(anuncio_id):
    # 1. Busca o anúncio ou dá erro 404 se não existir
    anuncio = Pedido.query.get_or_404(anuncio_id)
    
    # 2. Impede que o dono do anúncio clique no próprio botão
    if anuncio.usuario_id == current_user.id:
        return jsonify({"status": "erro", "mensagem": "Você não pode demonstrar interesse no seu próprio anúncio!"})

    # 3. Verifica se o interesse já foi registrado antes
    existente = Interesse.query.filter_by(
        anuncio_id=anuncio_id, 
        comprador_id=current_user.id
    ).first()

    if not existente:
        # 4. Se não existe, cria um novo registro
        novo_interesse = Interesse(
            anuncio_id=anuncio_id,
            comprador_id=current_user.id,
            vendedor_id=anuncio.usuario_id
        )
        db.session.add(novo_interesse)
        db.session.commit()
        return jsonify({"status": "sucesso", "mensagem": "Solicitação enviada ao vendedor!"})
    
    # 5. Se já existir, avisa o usuário
    return jsonify({"status": "ja_enviado", "mensagem": "Você já demonstrou interesse neste item."})

# --- ROTA PARA COMPLETAR PERFIL (PÓS-LOGIN) ---
@app.route('/completar_perfil', methods=['GET', 'POST'])
@login_required
def completar_perfil():
    if request.method == 'POST':
        # 1. Pegar dados do formulário
        current_user.nome = request.form.get('nome')
        current_user.bairro = request.form.get('bairro')
        current_user.bio = request.form.get('bio')
        
        # --- ADICIONADO APENAS ISSO ---
        zap_bruto = request.form.get('whatsapp', '')
        current_user.whatsapp = "".join(filter(str.isdigit, zap_bruto))
        
        # --- ADICIONE ESTAS DUAS LINHAS AQUI ---
        insta_bruto = request.form.get('instagram', '')
        current_user.instagram = insta_bruto.replace('@', '').strip()
        
        # 2. Lógica da Foto de Perfil com LIMPEZA
        file = request.files.get('foto')
        if file and file.filename != '':
            # --- INÍCIO DA FAXINA ---
            foto_antiga = current_user.foto_perfil
            # Verifica se não é a foto padrão antes de apagar
            if foto_antiga and foto_antiga != 'default_perfil.png':
                caminho_antigo = os.path.join(app.config['UPLOAD_FOLDER'], foto_antiga)
                if os.path.exists(caminho_antigo):
                    try:
                        os.remove(caminho_antigo)
                    except Exception as e:
                        print(f"Erro ao deletar foto antiga: {e}")
            # --- FIM DA FAXINA ---

            # Continua sua lógica original de salvar
            ext = os.path.splitext(file.filename)[1].lower()
            nome_foto = f"perfil_{current_user.id}_{int(time.time())}{ext}"
            
            pasta_perfil = os.path.join(app.config['UPLOAD_FOLDER'], 'perfil')
            if not os.path.exists(pasta_perfil):
                os.makedirs(pasta_perfil)
                
            caminho = os.path.join(pasta_perfil, nome_foto)
            
            img = Image.open(file)
            # Aplica a correção de rotação que colocamos na função salvar_foto
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except: pass

            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            img.save(caminho, optimize=True, quality=85)
            
            current_user.foto_perfil = f"perfil/{nome_foto}"

        db.session.commit()
        flash("Perfil atualizado com sucesso!")
        return redirect(url_for('exibir_mural'))
    
    # --- GET (Visualização da página) ---
    meus_interessados = Interesse.query.filter_by(vendedor_id=current_user.id).order_by(Interesse.data_solicitacao.desc()).all()
    Interesse.query.filter_by(vendedor_id=current_user.id, lido=False).update({'lido': True})
    db.session.commit()
        
    return render_template('completar_perfil.html', interessados=meus_interessados)

# --- ATUALIZE SUA ROTA DE LOGIN PARA ISSO ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_inf = request.form.get('email', '').lower().strip()
        senha_inf = request.form.get('senha')
        user = Usuario.query.filter_by(email=email_inf).first()
        
        if user and user.senha == senha_inf: # Verifique se você usa hash ou texto puro
            login_user(user)
            
                
            return redirect(url_for('exibir_mural'))
            
        flash("E-mail ou senha incorretos.")
    return render_template('login.html')


@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').lower().strip()
        senha = request.form.get('senha')
        
        if len(senha) < 8:
            # 1. Avisa o sistema do erro
            flash("A senha precisa de pelo menos 8 dígitos!", "erro")
            # 2. Manda o usuário de volta para a página de cadastro (sem tela branca)
            return redirect(url_for('cadastro_usuario'))
        
        try:
            novo_usuario = Usuario(nome=nome, email=email, senha=senha)
            db.session.add(novo_usuario)
            db.session.commit()
            login_user(novo_usuario)
            
            return redirect(url_for('completar_perfil'))
        except:
            return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html')

@app.route('/admin_mural')
@precisa_de_senha
def admin_mural():
    limpar_expirados()
    todos = Pedido.query.order_by(Pedido.id.desc()).all()
    vendas_lista = VendaEstatistica.query.all()
    total_vendas_realizadas = len(vendas_lista)
    stats_categorias = db.session.query(VendaEstatistica.categoria, func.count(VendaEstatistica.id)).group_by(VendaEstatistica.categoria).all()
    mais_acessados = Pedido.query.order_by(Pedido.acessos.desc()).limit(5).all()
    top_1 = mais_acessados[0] if mais_acessados else None
    faturamento = sum(15 if p.plano==2 else 5 for p in todos if p.is_premium and p.plano > 0)
    total_den = sum(1 for p in todos if (p.denuncias or 0) > 0)
    return render_template('admin.html', pedidos=todos, faturamento=faturamento, total_denuncias=total_den, total_vendas=total_vendas_realizadas, stats_categorias=stats_categorias, mais_acessados=mais_acessados, top_1=top_1, ultimos=todos[:5], pendentes=sum(1 for p in todos if p.plano_aguardando > 0 and p.plano == 0))

@app.route('/tornar_premium/<int:id>')
@precisa_de_senha
def tornar_premium(id):
    p = Pedido.query.get_or_404(id)
    if p.plano == 0 and p.plano_aguardando > 0:
        p.plano = p.plano_aguardando
        p.is_premium = True
        p.plano_aguardando = 0
    else:
        p.is_premium = not p.is_premium
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/limpar_denuncias/<int:id>')
@precisa_de_senha
def limpar_denuncias(id):
    p = Pedido.query.get_or_404(id)
    p.denuncias = 0  
    p.verificado = True # Torna o anúncio PERMANENTE (ninguém mais denuncia)
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/excluir_pedido/<int:id>')
@login_required
def excluir_pedido(id):
    p = Pedido.query.get_or_404(id)

    # --- CORREÇÃO DO BUG: LIMPAR INTERESSADOS ANTES ---
    # Isso remove qualquer "vínculo" que impede a exclusão no banco de dados
    Interesse.query.filter_by(pedido_id=id).delete()

    # Apagar as fotos (seu código original mantido)
    for f in [p.foto, p.foto2, p.foto3]:
        if f and f != 'sem-foto.jpg' and f != '':
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
            if os.path.exists(caminho): 
                os.remove(caminho)

    # Agora o banco de dados permite deletar o pedido
    db.session.delete(p)
    db.session.commit()
    
    return redirect(url_for('exibir_mural'))

@app.route('/zerar_estatisticas')
@precisa_de_senha
def zerar_estatisticas():
    VendaEstatistica.query.delete()
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/instalar')
def pagina_instalar():
    return render_template('instalar.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('exibir_mural'))

# --- ROTAS DE BACKUP (COLE AQUI) ---
@app.route('/baixar_banco')
@precisa_de_senha
def baixar_banco():
    try:
        # Envia o arquivo mural.db para download
        return send_from_directory(directory=BASE_DIR, path='mural.db', as_attachment=True)
    except Exception as e:
        return f"Erro ao baixar banco: {str(e)}"


# --------------------------------------

@app.route('/limpar_inativos_manual')
@precisa_de_senha
def limpar_inativos_manual():
    try:
        # Define o prazo de 3 meses (90 dias)
        prazo = datetime.now(timezone.utc) - timedelta(days=180)
        
        # Filtra usuários que não são admin e que o último acesso é antigo
        inativos = Usuario.query.filter(Usuario.ultimo_acesso < prazo).all()
        quantidade = len(inativos)
        
        for u in inativos:
            db.session.delete(u)
        
        db.session.commit()
        flash(f"✅ Limpeza concluída! {quantidade} contas inativas (6 meses+) foram removidas.")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erro na limpeza: {str(e)}")
        
    return redirect(url_for('admin_mural'))


@app.route('/anuncio/<int:id>')
def ver_anuncio_unico(id):
    p_real = Pedido.query.get_or_404(id)

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
            
            self.instagram = original.autor.instagram
            
            # ATRIBUTOS ESSENCIAIS PARA O MURAL NÃO TRAVAR:
            self.denuncias = 0  # Sem isso, o 'if pedido.denuncias' no HTML quebra
            self.verificado = True 
            self.is_premium = True 
            self.plano = 2 

    anuncio_para_exibir = AnuncioFake(p_real)
    return render_template('mural.html', pedidos=[anuncio_para_exibir], busca_ativa='', cat_ativa='')

@app.route('/api/anuncios_extras')
def anuncios_extras():
    anuncio_id = request.args.get('id', type=int)
    categoria = request.args.get('categoria')
    
    # Busca o anúncio atual para saber quem é o dono
    anuncio_atual = db.session.get(Pedido, anuncio_id)
    if not anuncio_atual:
        return jsonify({'do_vendedor': [], 'relacionados': []})

    # 1. Mais anúncios deste vendedor (limitado a 6)
    do_vendedor = Pedido.query.filter(
        Pedido.usuario_id == anuncio_atual.usuario_id, 
        Pedido.id != anuncio_id
    ).limit(6).all()

    # 2. Anúncios relacionados (mesma categoria, mas não do mesmo vendedor, limitado a 4)
    relacionados = Pedido.query.filter(
        Pedido.categoria == categoria, 
        Pedido.id != anuncio_id,
        Pedido.usuario_id != anuncio_atual.usuario_id
    ).limit(4).all()

    # Organiza os dados para enviar para o JavaScript
    return jsonify({
        'do_vendedor': [{
            'id': p.id,
            'titulo': p.titulo,
            'preco': float(p.preco) if p.preco else 0,
            'foto': p.foto
        } for p in do_vendedor],
        'relacionados': [{
            'id': p.id,
            'titulo': p.titulo,
            'preco': float(p.preco) if p.preco else 0,
            'foto': p.foto
        } for p in relacionados]
    })

if __name__ == '__main__':
    app.run(debug=True)