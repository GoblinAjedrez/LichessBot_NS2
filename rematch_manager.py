import asyncio
import logging
from typing import Any

from api import API
from botli_dataclasses import Challenge_Request, Game_Information
from config import Config
from enums import Challenge_Color, Variant

logger = logging.getLogger(__name__)

class Rematch_Manager:
    def __init__(self, api: API, config: Config, username: str) -> None:
        self.api = api
        self.config = config
        self.username = username
        
        # Track rematch history per opponent (opcional)
        self.rematch_counts: dict[str, int] = {}
        self.last_game_info: Game_Information | None = None
        self.pending_rematch: str | None = None
        self.rematch_offered: bool = False  # Track if rematch was already offered

    def should_offer_rematch(self, game_info: Game_Information, game_result: str, winner: str | None) -> bool:
        """
        Ofrecer SIEMPRE revancha, ignorando config/resultado/rating y sin límite.
        Solo evita duplicar si ya hay una oferta pendiente con ese mismo rival.
        """
        opponent_name = self._get_opponent_name(game_info)
        if not opponent_name:
            return False

        opponent_key = opponent_name.lower()

        # Evita repetir oferta si ya hay una revancha pendiente con este rival
        if self.pending_rematch == opponent_key:
            return False

        # No respetamos max_consecutive ni restricciones de rating: siempre True
        return True

    async def offer_rematch(self, game_info: Game_Information) -> bool:
        """Offer a rematch to the opponent (siempre)."""
        opponent_name = self._get_opponent_name(game_info)
        if not opponent_name:
            return False

        # Respeta el delay configurado si existe
        if getattr(self.config.rematch, "delay_seconds", 0) > 0:
            await asyncio.sleep(self.config.rematch.delay_seconds)

        # Crear challenge
        challenge_request = self._create_rematch_challenge(game_info, opponent_name)
        if not challenge_request:
            return False

        logger.debug('Offering rematch to %s...', opponent_name)
        
        # (Opcional) Contador de ofertas por rival
        opponent_key = opponent_name.lower()
        self.rematch_counts[opponent_key] = self.rematch_counts.get(opponent_key, 0) + 1
        logger.debug('Rematch count for %s is now: %d', opponent_name, self.rematch_counts[opponent_key])
        
        # Guardar estado de pendiente
        self.pending_rematch = opponent_key
        self.last_game_info = game_info
        self.rematch_offered = False  # Reset para el siguiente ciclo

        # La creación real del challenge la gestiona el game manager
        return True

    def on_rematch_accepted(self, opponent_name: str) -> None:
        """Cuando aceptan la revancha, limpiamos pendiente (seguiremos ofreciendo al terminar)."""
        self.pending_rematch = None
        self.rematch_offered = False
        opponent_key = opponent_name.lower()
        current_count = self.rematch_counts.get(opponent_key, 0)
        logger.debug('Rematch accepted by %s. Current count: %d', opponent_name, current_count)

    def on_rematch_declined(self, opponent_name: str) -> None:
        """Cuando rechazan, limpiamos pendiente y seguimos contando (volveremos a ofrecer tras el siguiente evento adecuado)."""
        self.pending_rematch = None
        self.rematch_offered = False
        opponent_key = opponent_name.lower()
        current_count = self.rematch_counts.get(opponent_key, 0)
        logger.debug('Rematch declined by %s. Count remains at: %d', opponent_name, current_count)

    def on_game_finished(self, opponent_name: str) -> None:
        """
        Al terminar una partida, no reseteamos conteos: queremos revancha todo el rato.
        También eliminamos el print con 'Rematch count preserved.'.
        """
        self.rematch_offered = False
        logger.debug('Game finished with %s.', opponent_name)

    def clear_pending_rematch(self) -> None:
        """Limpiar estado de revancha pendiente tras procesarse."""
        if self.pending_rematch:
            opponent_key = self.pending_rematch
            current_count = self.rematch_counts.get(opponent_key, 0)
            logger.debug('Clearing pending rematch with %s. Count remains at: %d', opponent_key, current_count)
        
        self.pending_rematch = None
        self.last_game_info = None
        self.rematch_offered = False

    def get_rematch_challenge_request(self) -> Challenge_Request | None:
        """Obtener el challenge de la revancha pendiente."""
        if not self.pending_rematch or not self.last_game_info:
            return None
        return self._create_rematch_challenge(self.last_game_info, self.pending_rematch)

    def _get_opponent_name(self, game_info: Game_Information) -> str | None:
        """Obtener el nombre del rival desde game_info."""
        if game_info.white_name.lower() == self.username.lower():
            return game_info.black_name
        elif game_info.black_name.lower() == self.username.lower():
            return game_info.white_name
        return None

    def _is_opponent_bot(self, game_info: Game_Information) -> bool:
        """Comprobar si el rival es bot (no usado para bloquear)."""
        if game_info.white_name.lower() == self.username.lower():
            return game_info.black_title == 'BOT'
        else:
            return game_info.white_title == 'BOT'

    def _check_rating_constraints(self, game_info: Game_Information) -> bool:
        """
        Mantengo el método por compatibilidad, pero NO se usa para bloquear.
        Devuelve siempre True.
        """
        return True

    def _get_our_rating(self, game_info: Game_Information) -> int | None:
        if game_info.white_name.lower() == self.username.lower():
            return game_info.white_rating
        else:
            return game_info.black_rating

    def _get_opponent_rating(self, game_info: Game_Information) -> int | None:
        if game_info.white_name.lower() == self.username.lower():
            return game_info.black_rating
        else:
            return game_info.white_rating

    def _create_rematch_challenge(self, game_info: Game_Information, opponent_name: str) -> Challenge_Request | None:
        """Crear el challenge de revancha (mismo control de tiempo/variante, colores invertidos)."""
        try:
            # Invertir colores
            if game_info.white_name.lower() == self.username.lower():
                color = Challenge_Color.BLACK
            else:
                color = Challenge_Color.WHITE

            # Parseo del control de tiempo
            initial_time_str, increment_str = game_info.tc_str.split('+')
            initial_time = int(float(initial_time_str) * 60)
            increment = int(increment_str)

            # Variante
            variant = Variant(game_info.variant)

            return Challenge_Request(
                opponent_name,
                initial_time,
                increment,
                game_info.rated,
                color,
                variant,
                self.config.rematch.timeout_seconds
            )
        except (ValueError, AttributeError) as e:
            logger.warning('Failed to create rematch challenge: %s', e)
            return None
