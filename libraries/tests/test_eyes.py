"""Offline rendering and driver-contract tests; no panels required."""
import hashlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from libraries.eyes.arby_eyes import EyeAnimator, STATES, normalize_state
from libraries.eyes.matrix_output import MatrixOutput


class EyesTests(unittest.TestCase):
    def test_all_states_native_frames(self):
        signatures=set()
        for state in STATES:
            animator=EyeAnimator(state)
            digest=hashlib.sha256()
            for t in (0,0.4,0.8,1.9,3.2):
                frame=animator.render(t)
                self.assertEqual(frame.size,(64,32))
                self.assertEqual(frame.mode,'RGB')
                for side in (0,1):
                    panel=frame.crop((32*side,0,32*side+32,32))
                    if state != "risa nerviosa":
                        self.assertIsNotNone(panel.crop((0,0,32,13)).getbbox())
                    self.assertIsNotNone(panel.crop((0,13,32,32)).getbbox())
                digest.update(frame.tobytes())
            signatures.add(digest.digest())
        self.assertEqual(len(signatures),27)

    def test_catalog_matches_bot_contract(self):
        from libraries.core.arby_response import MATRIX_STATES, make_segment
        from libraries.eyes.arby_eyes import EMOTION_STATES
        self.assertEqual(EMOTION_STATES, MATRIX_STATES)
        self.assertEqual(len(MATRIX_STATES), 25)
        for state in MATRIX_STATES:
            animator = EyeAnimator()
            animator.apply_response(make_segment("Hola", state), now=0)
            self.assertEqual(animator.state, state)

    def test_new_shapes_remain_visible_and_animated(self):
        for state in ("enamorados", "estrellas", "mareados", "gafas de sol",
                      "dolares", "aturdidos", "risa nerviosa"):
            animator = EyeAnimator(state)
            self.assertNotEqual(animator.render(0).tobytes(), animator.render(.8).tobytes())
            self.assertIsNotNone(animator.render(.8).crop((0, 13, 32, 32)).getbbox())

    def test_aliases_and_validation(self):
        self.assertEqual(normalize_state('Guiño_ojo'),'guiño ojo')
        self.assertEqual(normalize_state('Triste'),'triste')
        with self.assertRaises(ValueError):
            EyeAnimator('not-a-state')
        with self.assertRaises(TypeError):
            EyeAnimator(None)

    def test_transition_starts_at_current_pose(self):
        a=EyeAnimator('alegres')
        before=a.render(0.4).tobytes()
        a.set_state('enojado',now=0.4)
        self.assertEqual(before,a.render(0.4).tobytes())
        self.assertNotEqual(before,a.render(0.8).tobytes())
        b=EyeAnimator('enojado')
        self.assertEqual(a.render(0.8).tobytes(),b.render(0.8).tobytes())

    def test_repeated_state_does_not_restart_transition(self):
        a=EyeAnimator()
        a.set_state('triste',now=1)
        a.set_state('triste',now=1.1)
        self.assertEqual(a._start,1)

    def test_deterministic_exports(self):
        a,b=EyeAnimator('locos'),EyeAnimator('locos')
        self.assertEqual(a.render(0.45).tobytes(),b.render(0.45).tobytes())

    def test_wink_is_one_sided(self):
        frame=EyeAnimator('guiño ojo').render(0.8)
        self.assertNotEqual(frame.crop((0,0,32,32)).tobytes(),
                            frame.crop((32,0,64,32)).tobytes())

    def test_system_states_and_default(self):
        self.assertEqual(EyeAnimator().state, 'default')
        self.assertEqual(normalize_state('Reposo'), 'default')
        self.assertEqual(normalize_state('Loading'), 'cargando')
        self.assertNotEqual(EyeAnimator('default').render(0).tobytes(),
                            EyeAnimator('cargando').render(0).tobytes())

    def test_all_state_transitions(self):
        for initial in STATES:
            for target in STATES:
                with self.subTest(initial=initial, target=target):
                    animator = EyeAnimator(initial)
                    before = animator.render(0.4).tobytes()
                    animator.set_state(target, now=0.4)
                    self.assertEqual(before, animator.render(0.4).tobytes())
                    self.assertEqual(animator.render(0.8).tobytes(),
                                     EyeAnimator(target).render(0.8).tobytes())

    def test_mux_required(self):
        with self.assertRaises(ValueError):
            MatrixOutput(multiplexing=None)

    def test_bot_response_colors_both_panels_and_brows(self):
        animator = EyeAnimator()
        animator.apply_response({
            'matrix_state': 'enojado',
            'strip_led': {'color': {'r': 255, 'g': 0, 'b': 0}, 'mood': 'enojado'},
            'response': 'Example speech',
        }, now=0)
        frame = animator.render(0.4)
        for side in (0, 1):
            for area in ((32*side, 0, 32*side+32, 13),
                         (32*side, 13, 32*side+32, 32)):
                colors = {rgb for count, rgb in frame.crop(area).getcolors(maxcolors=1024)}
                self.assertIn((255, 0, 0), colors)
        self.assertEqual(animator.style.highlight_color, (245, 255, 255))

    def test_invalid_response_never_changes_state_or_color(self):
        animator = EyeAnimator('alegres')
        original_style = animator.style
        for color in ({'r': 256, 'g': 0, 'b': 0},
                      {'r': True, 'g': 0, 'b': 0},
                      {'r': 1, 'g': 0}, 'red'):
            with self.subTest(color=color), self.assertRaises(ValueError):
                animator.apply_response({
                    'matrix_state': 'enojado',
                    'strip_led': {'color': color, 'mood': 'enojado'},
                })
            self.assertEqual(animator.state, 'alegres')
            self.assertEqual(animator.style, original_style)
        with self.assertRaises(ValueError):
            animator.apply_response({'matrix_state': 'enojado', 'strip_led': {
                'color': {'r': 255, 'g': 0, 'b': 0}, 'mood': 'triste'}})
        self.assertEqual(animator.state, 'alegres')
        self.assertEqual(animator.style, original_style)

    def test_color_updates_without_restarting_expression(self):
        animator = EyeAnimator()
        animator.set_state('alegres', color=(0, 255, 80), now=1)
        animator.set_state('alegres', color={'r': 255, 'g': 0, 'b': 0}, now=2)
        self.assertEqual(animator._start, 1)
        self.assertEqual(animator.style.eye_color, (255, 0, 0))

    def test_system_states_restore_idle_colors(self):
        animator = EyeAnimator()
        original_style = animator.style
        for system_state in ('default', 'cargando'):
            animator.set_state('enojado', color=(255, 0, 0))
            animator.set_state(system_state)
            self.assertEqual(animator.style, original_style)

    def test_matrix_adapter_contract(self):
        class FakeCanvas:
            def SetImage(self,image):
                self.image=image
        class FakeMatrix:
            def __init__(self,options):
                if getattr(options, 'drop_privileges', True):
                    raise PermissionError('Matrix initialization would drop access to the project')
                self.options=options
                self.width,self.height=64,32
                self.cleared=False
            def CreateFrameCanvas(self):
                return FakeCanvas()
            def SwapOnVSync(self,canvas):
                self.displayed=canvas.image
                return FakeCanvas()
            def Clear(self):
                self.cleared=True
        fake=SimpleNamespace(RGBMatrix=FakeMatrix,RGBMatrixOptions=SimpleNamespace)
        with patch.dict(sys.modules,{'rgbmatrix':fake}):
            adapter=MatrixOutput(multiplexing=1,swap_eyes=True)
            frame=EyeAnimator('duda').render(0)
            adapter.show(frame)
            self.assertEqual(adapter.matrix.options.hardware_mapping,'regular')
            self.assertEqual(adapter.matrix.options.chain_length,2)
            self.assertEqual(adapter.matrix.displayed.crop((0,0,32,32)).tobytes(),
                             frame.crop((32,0,64,32)).tobytes())
            adapter.close()
            self.assertTrue(adapter.matrix.cleared)
            custom = MatrixOutput(multiplexing=6, hardware_mapping='regular-oe5', rgb_sequence='BGR')
            self.assertEqual(custom.matrix.options.led_rgb_sequence, 'BGR')
            self.assertTrue(custom.matrix.options.disable_hardware_pulsing)
            custom.close()


if __name__=='__main__':
    unittest.main()
