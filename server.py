import socket
import pyaudio
import os
from pydub import AudioSegment
import json
from _thread import start_new_thread
import threading
import select

from flask import Flask, request, jsonify, render_template

import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Diccionario para almacenar conexiones de clientes
clients = {}

# Configuración de audio
CHUNK = 2048
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100

class Client:
    def __init__(self, client_ip, audio_conn, command_conn):
        self.client_ip = client_ip
        self.audio_conn = audio_conn
        self.command_conn = command_conn
        self.paused = False
        self.stopped = False
        self.volume = 1.0  # Rango de 0.0 a 1.0
        self.pause_event = threading.Event()

def handle_client(audio_conn, audio_address, command_conn, command_address):
    print(f"<{audio_address}> conectado")
    
    clients[audio_address] = Client(audio_address, audio_conn, command_conn)

    inputs = [audio_conn, command_conn]
    
    while inputs:
        readable, _, _ = select.select(inputs, [], [])
        
        for sock in readable:
            if sock is audio_conn:
                data_audio = sock.recv(1024).decode()
                if not data_audio:
                    print(f"Conexión de audio cerrada {audio_address}")
                    inputs.remove(audio_conn)
                    audio_conn.close()
                else:
                    print(f"Data de audio recibida: {data_audio}")
            
            elif sock is command_conn:
                data_command = sock.recv(1024).decode()
                if not data_command:
                    print(f"Conexión de comandos cerrada {command_address}")
                    inputs.remove(command_conn)  
                    command_conn.close()
                else:
                    print(f"Data de comandos recibida: {data_command}")
    
    print(f"Conexiones cerradas {audio_address}")
    del clients[audio_address]

def send_audio(client, file_path):
    audio = AudioSegment.from_mp3(file_path)
    audio = audio.set_channels(CHANNELS).set_frame_rate(RATE).set_sample_width(2)
    
    chunks = [audio[i:i + (CHUNK * 1000 // RATE)] for i in range(0, len(audio), (CHUNK * 1000 // RATE))]
    frame_position = 0

    while not client.pause_event.is_set() and frame_position < len(chunks):
        print(f"Enviando audio para {client.client_ip}")
        chunk = chunks[frame_position]
        client.audio_conn.send(chunk.raw_data)
        frame_position += 1
                
    # Se indica que el hilo ha terminado
    client.pause_event.set()
    
    print(f"Audio enviado {file_path}")

def send_command(command_conn,command):
    command_conn.send(command.encode())
  

def get_client_by_ip(client_ip):
    for client in clients.values():
        if client.client_ip[0] == client_ip:
            return client
    return None
    
@app.route('/')
def index():
    songs = [f.replace('.mp3', '') for f in os.listdir('./resource') if f.endswith('.mp3')]
    return render_template('index.html', clients=clients.values(), songs=songs)

@app.route('/play', methods=['POST'])
def play_audio():
    try:
        client_ip = request.form['client_ip']
        song = request.form['song']
        volume = int(request.form['volume'])

        if os.path.exists(f'./resource/{song}.mp3'):
            file_path = f'./resource/{song}.mp3'
        else:
            return jsonify({'message': 'Audio no encontrado'}), 404

        client = get_client_by_ip(client_ip)
        if not client:
            return jsonify({'message': f'No hay una conexión activa para {client_ip}'}), 404

        # Si el cliente ya tiene un hilo de audio corriendo y está pausado, solo se envía resume
        if client.paused:
            send_command(client.command_conn, "resume")
            client.paused = False
            return jsonify({'message': f'Audio resumido para {client_ip}'}), 200
        
        if client.pause_event.is_set():
            client.pause_event.wait()

        if client.stopped:
            client.stopped = False
        
        client.pause_event.set()
        client.pause_event = threading.Event()

        # Se envía el comando de volumen
        send_command(client.command_conn, f"volume:{volume}")

        # Se inicia el hilo de audio
        start_new_thread(send_audio, (client, file_path))

        return jsonify({'message': 'Envio iniciado para {client_ip}'}), 200
    except Exception as e:
        logging.error(f"Error: {e}")
        return jsonify({'message': f'Error: {e}'}), 500


@app.route('/volume', methods=['POST'])
def adjust_volume():
    try:
        client_ip =  request.form['client_ip']
        volume = request.form['volume']
        client = get_client_by_ip(client_ip)
        if client:
            send_command(client.command_conn,f"volume:{volume}")
            return jsonify({'message': f'Volumen: {volume} para {client.client_ip}'})
        return jsonify({'message': f'No se encontró el cliente {client.client_ip}'}), 404
    except Exception as e:
        return jsonify({'message': f'Error: {e}'}), 500
    
@app.route('/pause', methods=['POST'])
def pause_audio():
    try:
        client_ip = request.form['client_ip']
        client = get_client_by_ip(client_ip)

        if client:
            send_command(client.command_conn, "pause")
            client.paused = True

        return jsonify({'message': f'Audio pausado para {client_ip}'}), 200
    except Exception as e:
        return jsonify({'message': f'Error: {e}'}), 500       

@app.route('/stop', methods=['POST'])
def stop_audio():
    try:
        client_ip = request.form['client_ip']
        client = get_client_by_ip(client_ip)

        if client:
            client.pause_event.set()  # Se detiene el hilo actual
            client.stopped = True
            client.paused = False
            send_command(client.command_conn, "stop")


        return jsonify({'message': f'Audio detenido para {client_ip}'}), 200
    except Exception as e:
        return jsonify({'message': f'Error: {e}'}), 500


def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    start_new_thread(run_flask, ())
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("", 5544))
    server_socket.listen(10)

    command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    command_socket.bind(("", 5533))
    command_socket.listen(10)
    
    while True:
        audio_conn, audio_address = server_socket.accept()
        command_conn, command_address = command_socket.accept()
        
        start_new_thread(handle_client, (audio_conn, audio_address, command_conn, command_address))



