#!/usr/bin/env python3
"""Avisos do Sistema Mauer no WhatsApp (Z-API ou CallMeBot) ou no Telegram,
e fechamento automático das separações que ficaram abertas depois das 18h.

Roda no GitHub Actions a cada 5 minutos. Lê o banco (Firebase), vê o que está atrasado
ou precisa do responsável e manda UMA mensagem por filial no grupo (ou nos números) dela.
Cada aviso é enviado uma vez só (fica marcado em avisosEnviados).
Configuração: painel do gestor → Avisos (grava em configuracoes/avisos).
"""
import json, os, re, sys, time, urllib.request, urllib.parse, unicodedata
from datetime import datetime, timedelta, timezone

FB = os.environ.get('FIREBASE_URL', 'https://mauer-produtividade-default-rtdb.firebaseio.com').rstrip('/')
TG = os.environ.get('TELEGRAM_API', 'https://api.telegram.org').rstrip('/')
ZAPI = os.environ.get('ZAPI_API', 'https://api.z-api.io').rstrip('/')
CMB = os.environ.get('CALLMEBOT_API', 'https://api.callmebot.com').rstrip('/')
BR = timezone(timedelta(hours=-3))
AGORA = float(os.environ.get('AGORA_TESTE_MS') or time.time() * 1000)   # AGORA_TESTE_MS só para testes
MIN = 60000


def req(url, metodo='GET', corpo=None, headers=None):
    data = None if corpo is None else json.dumps(corpo).encode()
    r = urllib.request.Request(url, data=data, method=metodo, headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode() or 'null')


def fb(path, **q):
    url = f'{FB}/{path}.json'
    if q:
        url += '?' + urllib.parse.urlencode({k: json.dumps(v) for k, v in q.items()})
    try:
        return req(url) or {}
    except urllib.error.HTTPError as e:
        if q and e.code == 400:      # sem índice no Firebase: lê tudo e filtra aqui
            todos = req(f'{FB}/{path}.json') or {}
            campo = q.get('orderBy')
            if 'equalTo' in q:
                return {k: v for k, v in todos.items() if isinstance(v, dict) and v.get(campo) == q['equalTo']}
            return {k: v for k, v in todos.items() if isinstance(v, dict) and str(v.get(campo, '')) >= str(q.get('startAt'))}
        raise


def dia(dias_atras=0):
    return (datetime.now(BR) - timedelta(days=dias_atras)).strftime('%Y-%m-%d')


def norm_ped(x):
    return re.sub(r'^0+', '', re.sub(r'\D', '', str(x or '')))


def chave_filial(n):
    s = unicodedata.normalize('NFD', str(n or '')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+', '_', s).strip('_')


def dur(m):
    m = max(0, round(m))
    return f'{m} min' if m < 60 else f'{m // 60}h{m % 60:02d}'


def hora(ts):
    return datetime.fromtimestamp(ts / 1000, BR).strftime('%H:%M')


def provedor(cfg):
    return cfg.get('provedor') or 'telegram'


def pronto(cfg):
    p = provedor(cfg)
    if p == 'zapi':
        z = cfg.get('zapi') or {}
        return bool(z.get('instancia') and z.get('token'))
    if p == 'callmebot':
        return True
    return bool(cfg.get('token'))


def zapi_base(cfg):
    z = cfg.get('zapi') or {}
    return f"{ZAPI}/instances/{z.get('instancia')}/token/{z.get('token')}", ({'Client-Token': z['clientToken']} if z.get('clientToken') else {})


def enviar(cfg, destino, texto):
    """Manda o texto para um destino. Devolve True se pelo menos um envio deu certo."""
    destino = str(destino or '').strip()
    if not destino:
        return False
    p = provedor(cfg)
    if p == 'zapi':
        base, h = zapi_base(cfg)
        req(f'{base}/send-text', 'POST', {'phone': destino, 'message': texto}, h)
        return True
    if p == 'callmebot':
        ok = False
        for par in re.split(r'[;,\n]+', destino):        # "5511999990000:APIKEY; 5511988880000:APIKEY"
            if ':' not in par:
                continue
            fone, chave = [x.strip() for x in par.split(':', 1)]
            fone = re.sub(r'\D', '', fone)
            url = f"{CMB}/whatsapp.php?" + urllib.parse.urlencode({'phone': '+' + fone, 'text': texto, 'apikey': chave})
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    ok = ok or r.status == 200
            except Exception as e:
                print('Falha CallMeBot em um número:', type(e).__name__)
            time.sleep(2)
        return ok
    req(f"{TG}/bot{cfg['token']}/sendMessage", 'POST', {'chat_id': destino, 'text': texto, 'disable_web_page_preview': True})
    return True


def pedidos_do_painel(cfg):
    """Atende os botões do painel: mensagem de teste e busca de grupos do WhatsApp."""
    upd = {}
    teste = cfg.get('teste')
    if isinstance(teste, dict) and teste.get('destino') and not teste.get('resultado'):
        try:
            ok = enviar(cfg, teste['destino'], f"✅ Teste do Sistema Mauer: os avisos da {teste.get('nome', 'filial')} vão chegar aqui.")
            upd['teste/resultado'] = 'ok' if ok else 'falhou'
        except Exception as e:
            upd['teste/resultado'] = 'falhou: ' + type(e).__name__
        upd['teste/em'] = int(AGORA)
    if cfg.get('buscarGrupos') and provedor(cfg) == 'zapi':
        try:
            base, h = zapi_base(cfg)
            lista = req(f'{base}/groups?page=1&pageSize=200', headers=h) or []
            upd['gruposEncontrados'] = [{'id': g.get('phone'), 'nome': g.get('name') or g.get('phone')} for g in lista if isinstance(g, dict) and g.get('phone')]
        except Exception as e:
            upd['gruposEncontrados'] = [{'id': '', 'nome': 'Falhou ao buscar: ' + type(e).__name__}]
        upd['buscarGrupos'] = None
        upd['gruposEm'] = int(AGORA)
    if upd:
        req(f'{FB}/configuracoes/avisos.json', 'PATCH', upd)


def fechar_separacoes():
    """Fecha sozinho as separações que ficaram abertas depois do horário de corte (padrão 18h).
    Só mexe em lotes "em separação" iniciados por separadores; não toca na fila do Aro nem na conferência.
    Lote iniciado antes do corte: fim = horário do corte daquele dia.
    Lote iniciado depois do corte (turno da noite): fica aberto e é fechado às 23:59 do mesmo dia."""
    cfg = fb('configuracoes/fechamentoAuto') or {}
    if cfg.get('ativo') is False:
        return 0
    hora = int(cfg.get('hora', 18))
    agora = datetime.fromtimestamp(AGORA / 1000, BR)
    abertos = fb('registros', orderBy='status', equalTo='em_separacao')
    upd = {}
    for k, r in (abertos or {}).items():
        if not isinstance(r, dict) or r.get('status') != 'em_separacao' or not r.get('inicio'):
            continue
        ini = datetime.fromtimestamp(r['inicio'] / 1000, BR)
        corte = ini.replace(hour=hora, minute=0, second=0, microsecond=0)
        if ini < corte:
            fim = corte
        else:
            fim = ini.replace(hour=23, minute=59, second=0, microsecond=0)
        if agora < fim:
            continue
        fim_ms = int(fim.timestamp() * 1000)
        for campo, valor in {'fim': fim_ms, 'duracaoMin': round((fim_ms - r['inicio']) / MIN), 'status': 'finalizado', 'finalizadoAuto': True,
                             'finalizadoPor': f'fechamento automático {hora}h' if ini < corte else 'fechamento automático 23h59'}.items():
            upd[f'{k}/{campo}'] = valor
    if upd:
        req(f'{FB}/registros.json', 'PATCH', upd)
    n = len({c.split('/')[0] for c in upd})
    print(f'Separações fechadas automaticamente: {n}')
    return n


def main():
    try:
        fechar_separacoes()
    except Exception as e:
        print('Fechamento automático falhou:', type(e).__name__)
    cfg = fb('configuracoes/avisos') or {}
    if pronto(cfg):
        pedidos_do_painel(cfg)
    if not cfg.get('ativo') or not pronto(cfg):
        print('Avisos desligados ou sem configuração. Nada a fazer.')
        return
    tipos = cfg.get('tipos') or {}
    liga = lambda t: tipos.get(t, True)
    h = datetime.now(BR).hour
    hi, hf = int(cfg.get('horaIni', 0)), int(cfg.get('horaFim', 24))
    silencio = not (hi <= h < hf) if hi < hf else not (h >= hi or h < hf)

    prazos = {'fila': 60, 'conferencia': 30, **(fb('configuracoes/prazosEtapas') or {})}
    meta_h = float(fb('configuracoes/metaPneusHora') or 50) or 50
    enviados = fb('avisosEnviados') or {}

    ini3 = dia(3)
    fila = fb('filaPedidos', orderBy='data', startAt=dia(14))
    regs = fb('registros', orderBy='data', startAt=dia(7))
    lancs = fb('lancamentos', orderBy='data', startAt=ini3)
    confs = fb('confirmacoes', orderBy='data', startAt=dia(30))
    bloqs = fb('bloqueiosDup')
    dups = fb('alertasDuplicado', orderBy='data', startAt=dia(1))

    conferidos = {norm_ped(c.get('numPedido')) + '|' + str(c.get('filial')) for c in confs.values() if isinstance(c, dict)}
    avisos = {}   # filial -> lista de (chave, texto)

    def add(filial, chave, texto):
        if chave in enviados:
            return
        avisos.setdefault(filial or 'Sem filial', []).append((chave, texto))

    if liga('fila'):
        for k, f in fila.items():
            if isinstance(f, dict) and f.get('status') == 'disponivel' and f.get('criadoEm'):
                m = (AGORA - f['criadoEm']) / MIN
                if m > prazos['fila']:
                    add(f.get('filial'), 'fila_' + k, f"📥 Pedido {f.get('num')} está na fila do Aro há {dur(m)} sem separador (prazo {prazos['fila']} min)")
    if liga('separacao'):
        for k, r in regs.items():
            if isinstance(r, dict) and r.get('status') == 'em_separacao' and r.get('inicio'):
                meta = max(5, -(-float(r.get('totalPneus') or 0) * 60 // meta_h))
                m = (AGORA - r['inicio']) / MIN
                if m > meta:
                    nums = ', '.join(str(p.get('num')) for p in (r.get('pedidos') or []) if isinstance(p, dict))
                    add(r.get('filial'), 'sep_' + k, f"🐢 {r.get('colaborador')} está separando há {dur(m)} (limite {int(meta)} min) · pedidos {nums}")
    if liga('conferencia'):
        vistos = set()
        for k, l in lancs.items():
            if not isinstance(l, dict) or not l.get('isPedido') or not l.get('numPedido'):
                continue
            chave = norm_ped(l['numPedido']) + '|' + str(l.get('filial'))
            if chave in conferidos or chave in vistos:
                continue
            vistos.add(chave)
            reg = regs.get(l.get('registroId')) if l.get('registroId') else None
            if reg and reg.get('status') == 'em_separacao':
                continue
            desde = (reg or {}).get('fim') or l.get('timestamp')
            if not desde:
                continue
            m = (AGORA - desde) / MIN
            if m > prazos['conferencia']:
                add(l.get('filial'), 'conf_' + k, f"📋 Pedido {l['numPedido']} ({l.get('colaborador')}) esperando conferência há {dur(m)} (prazo {prazos['conferencia']} min)")
    if liga('bloqueio'):
        for k, b in bloqs.items():
            if isinstance(b, dict):
                add(b.get('filial'), f"bloq_{k}_{int(b.get('desde') or 0)}", f"🔒 {b.get('colaborador')} está BLOQUEADO desde {hora(b.get('desde') or AGORA)}: tentou lançar pedido duplicado ({', '.join(b.get('pedidos') or [])}). Precisa da palavra-chave do responsável.")
    if liga('duplicado'):
        for k, a in dups.items():
            if isinstance(a, dict) and a.get('numPedido') and not a.get('liberacao') and (AGORA - (a.get('timestamp') or 0)) < 3 * 3600 * 1000:
                res = 'bloqueado' if a.get('bloqueado') else ('liberado por ' + a['autorizadoPor'] if a.get('autorizadoPor') else 'só avisou')
                add(a.get('filial'), 'dup_' + k, f"⚠️ Pedido {a.get('numPedido')} duplicado ({res}) · {a.get('quem') or ''}")

    destinos = cfg.get('filiais') or {}
    geral = str(cfg.get('destinoGeral') or cfg.get('chatGeral') or '').strip()
    marcar, total = {}, 0
    for filial, itens in avisos.items():
        chats = []
        d = destinos.get(chave_filial(filial)) or {}
        dest = str(d.get('destino') or d.get('chatId') or '').strip()
        if dest and d.get('ativo', True):
            chats.append(dest)
        if geral and geral not in chats:
            chats.append(geral)
        if not chats:
            continue                                   # filial sem grupo: não marca, manda quando configurar
        if silencio:
            continue                                   # fora do horário: manda quando abrir o horário
        corpo = f"⏰ {filial} — {len(itens)} aviso(s)\n\n" + '\n'.join('• ' + t for _, t in itens[:25])
        if len(itens) > 25:
            corpo += f'\n… e mais {len(itens) - 25}. Veja no painel do gestor.'
        ok = False
        for chat in chats:
            try:
                ok = enviar(cfg, chat, corpo) or ok
            except Exception as e:
                print('Falha ao enviar para um grupo:', type(e).__name__)
        if ok:
            total += len(itens)
            for chave, _ in itens:
                marcar[chave] = int(AGORA)

    # limpa marcas com mais de 7 dias
    for k, t in enviados.items():
        if isinstance(t, (int, float)) and AGORA - t > 7 * 864e5:
            marcar[k] = None
    if marcar:
        req(f'{FB}/avisosEnviados.json', 'PATCH', marcar)
    print(f'Avisos enviados: {total} · filiais com aviso: {len(avisos)} · silêncio: {silencio}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Erro:', type(e).__name__, str(e)[:200])
        sys.exit(1)
