import time
import threading
from .coin import Coin
from .crypto import Crypto
from .messages import Messages
from .commutator_thread import Commutator, Channel, ChannelWithPrint
from .phase import Phase
from .coin_shuffle import Round

class ProtocolThread(threading.Thread):
    """
    This class emulate thread with protocol run
    """
    def __init__(self, host, port, network,
                 amount, fee, sk, pubk,
                 addr_new, change, logger=None, ssl=False):

        threading.Thread.__init__(self)
        self.host = host
        self.port = port
        self.ssl = ssl
        self.messages = Messages()
        self.income = Channel()
        self.outcome = Channel()
        if not logger:
            self.logger = ChannelWithPrint()
        else:
            self.logger = logger
        self.commutator = Commutator(self.income, self.outcome, ssl=ssl)
        self.vk = pubk
        self.session = None
        self.number = None
        self.number_of_players = None
        self.players = {}
        self.amount = amount
        self.fee = fee
        self.sk = sk
        self.addr_new = addr_new
        self.change = change
        self.deamon = True
        self.protocol = None
        self.network = network
        self.tx = None
        self.execution_thread = None
        self.done = threading.Event()

    def not_time_to_die(func):
        "Check if 'done' event appear"
        def wrapper(self):
            if not self.done.is_set():
                func(self)
            else:
                pass
        return wrapper

    @not_time_to_die
    def register_on_the_pool(self):
        "This method trying to register player on the pool"
        self.messages.make_greeting(self.vk, int(self.amount))
        msg = self.messages.packets.SerializeToString()
        self.income.send(msg)
        req = self.outcome.recv()
        self.messages.packets.ParseFromString(req)
        self.session = self.messages.packets.packet[-1].packet.session
        self.number = self.messages.packets.packet[-1].packet.number
        if self.session != '':
            self.logger.send("Player "  + str(self.number)+" get session number.\n")

    @not_time_to_die
    def wait_for_announcment(self):
        "This method waits for announcement messages from other pool"
        while self.number_of_players is None:
            req = self.outcome.recv()
            if self.done.is_set():
                break
            if req is None:
                time.sleep(0.1)
                continue
            try:
                self.messages.packets.ParseFromString(req)
            except:
                continue
            if self.messages.get_phase() == 1:
                self.number_of_players = self.messages.get_number()
                break
            else:
                self.logger.send("Player " + str(self.messages.get_number()) + " joined the pool!")

    @not_time_to_die
    def share_the_key(self):
        "This method shares the verification keys among the players in the pool"
        self.logger.send("Player " + str(self.number) + " is about to share verification key with "
                         + str(self.number_of_players) +" players.\n")
        #Share the keys
        self.messages.clear_packets()
        self.messages.packets.packet.add()
        self.messages.packets.packet[-1].packet.from_key.key = self.vk
        self.messages.packets.packet[-1].packet.session = self.session
        self.messages.packets.packet[-1].packet.number = self.number
        shared_key_message = self.messages.packets.SerializeToString()
        self.income.send(shared_key_message)

    @not_time_to_die
    def gather_the_keys(self):
        "This method gather the verification keys from other players in the pool"
        messages = b''
        for _ in range(self.number_of_players):
            messages += self.outcome.recv()
        self.messages.packets.ParseFromString(messages)
        self.players = {packet.packet.number:str(packet.packet.from_key.key)
                        for packet in self.messages.packets.packet}
        if self.players:
            self.logger.send('Player ' +str(self.number)+ " get " + str(len(self.players))+".\n")
        #check if all keys are different
        if len(set(self.players.values())) is not self.number_of_players:
            self.logger.send('Error: The same keys appears!')
            self.done.set()

    @not_time_to_die
    def start_protocol(self):
        "This method starts the protocol thread"
        coin = Coin(self.network)
        crypto = Crypto()
        self.messages.clear_packets()
        begin_phase = Phase('Announcement')
        # Make Round
        self.protocol = Round(
            coin,
            crypto,
            self.messages,
            self.outcome,
            self.income,
            self.logger,
            self.session,
            begin_phase,
            self.amount,
            self.fee,
            self.sk,
            self.vk,
            self.players,
            self.addr_new,
            self.change)
        self.execution_thread = threading.Thread(target=self.protocol.protocol_loop)
        self.execution_thread.start()
        self.done.wait()
        self.execution_thread.join()


    def run(self):
        "this method trying to run the round and catch possible problems with it"
        try:
            self.commutator.connect(self.host, self.port)
            self.commutator.start()
        except:
            self.logger.send("Error: cannot connect to server")
        try:
            self.register_on_the_pool()
        except:
            self.logger.send("Error: cannot register on the pool")
        try:
            self.wait_for_announcment()
        except:
            self.logger.send("Error: cannot complete the pool")
        try:
            self.share_the_key()
        except:
            self.logger.send("Error: cannot share the keys")
        try:
            self.gather_the_keys()
        except:
            self.logger.send("Error: cannot gather the keys")
        self.start_protocol()
        if self.commutator.is_alive():
            self.commutator.join()


    def stop(self):
        "This method stops the protocol threads"
        if self.execution_thread:
            self.protocol.done = True
        self.done.set()
        self.outcome.send(None)


    def join(self, timeout=None):
        "This method Joins the protocol thread"
        self.stop()
        threading.Thread.join(self, timeout)
