from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, modes

try:
    # Try new import path first (cryptography 41.0.0+)
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except ImportError:
    # Fall back to old import path for older versions
    from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
import base64


class DataProtector:
    _instance: "DataProtector | None" = None
    __initialized: bool

    # define new to handle signleton logic
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(DataProtector, cls).__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self):
        if not self.__initialized:
            self.__key = base64.b64decode("N+18ODsflI+oW8geU+g4sQ==")
            self.__iv = base64.b64decode("sPojjWkKXRE=")
            self.__crypto_provider = TripleDES(self.__key)
            self.__initialized = True

    # encrypts plaintext to bytes
    def encryptToBytes(self, plaintext):
        # check if plaintext is empty or null
        if not plaintext:
            return None

        # create cipher object
        cipher = Cipher(self.__crypto_provider, modes.CBC(self.__iv))
        encryptor = cipher.encryptor()

        # convert plaintext to bytes
        plaintext_bytes = plaintext.encode("utf-8")
        # pad the plaintext
        padder = padding.PKCS7(64).padder()
        padded_data = padder.update(plaintext_bytes) + padder.finalize()
        # encrypt the padded plaintext
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return ciphertext

    # decrypts bytes to plaintext
    def decryptFromBytes(self, encryptedBytes):
        # if encryptedBytes is empty or null
        if encryptedBytes is None or len(encryptedBytes) == 0:
            return None
        try:
            # create cipher object
            cipher = Cipher(self.__crypto_provider, modes.CBC(self.__iv))
            decryptor = cipher.decryptor()
            # decrypt the encrypted bytes
            decryptedBytes = decryptor.update(encryptedBytes) + decryptor.finalize()
            # unpad the decrypted bytes
            unpadder = padding.PKCS7(64).unpadder()
            plaintext_bytes = unpadder.update(decryptedBytes) + unpadder.finalize()
            return plaintext_bytes
        except Exception:
            return None

    # encrypts plain text, returns a base64 string
    def encrypt(self, plaintext):
        encryptedBytes = self.encryptToBytes(plaintext)
        if encryptedBytes is not None and len(encryptedBytes) > 0:
            # convert the encrypted bytes to a base64 string
            return base64.b64encode(encryptedBytes).decode("utf-8")
        return None

    # encrypts a plain text to a url safe value, whcih does not
    # contain any special characters
    def encryptUrlSafe(self, plaintext):
        # encrypt the plain text to bytes
        encryptedBytes = self.encryptToBytes(plaintext)
        if encryptedBytes is not None and len(encryptedBytes) > 0:
            # convert the encrypted bytes to a url safe string by hex encoding
            return encryptedBytes.hex()
        return None

    # decrypts a base64 string to plain text
    def decrypt(self, encryptedText):
        if encryptedText is None or len(encryptedText) == 0:
            return None
        try:
            # convert the base64 string to bytes then decrypt
            decrypted_bytes = self.decryptFromBytes(base64.b64decode(encryptedText))
            return decrypted_bytes.decode("utf-8") if decrypted_bytes is not None else None
        except Exception:
            return None

    # decrypts a url safe string to plain text
    def decryptUrlSafe(self, encryptedText):
        if encryptedText is None or len(encryptedText) == 0:
            return None
        # convert the url safe string to bytes then decrypt
        decrypted_bytes = self.decryptFromBytes(bytes.fromhex(encryptedText))
        return decrypted_bytes.decode("utf-8") if decrypted_bytes is not None else None
