"""Run the pixel preview, or the optional real-matrix output."""
import argparse
import time

try:
    from .arby_eyes import EyeAnimator, STATES
except ImportError:
    from arby_eyes import EyeAnimator, STATES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['preview','matrix'],default='preview')
    parser.add_argument('--state',default='default')
    parser.add_argument('--color', type=int, nargs=3, metavar=('R', 'G', 'B'))
    parser.add_argument('--multiplexing',type=int)
    parser.add_argument('--row-address-type',type=int,default=0)
    parser.add_argument('--brightness',type=int,default=25)
    parser.add_argument('--slowdown',type=int,default=2)
    parser.add_argument('--swap-eyes',action='store_true')
    parser.add_argument('--auto',action='store_true')
    args=parser.parse_args()
    animator=EyeAnimator(args.state)
    if args.color is not None:
        try:
            animator.set_state(args.state, color=args.color)
        except ValueError as exc:
            parser.error(str(exc))
    if args.backend=='matrix':
        if args.multiplexing is None:
            parser.error('No se ha validado el multiplexado. Especifica --multiplexing cuando tengas los paneles.')
        try:
            from .matrix_output import MatrixOutput
        except ImportError:
            from matrix_output import MatrixOutput
        output=MatrixOutput(multiplexing=args.multiplexing,slowdown=args.slowdown,
                            brightness=args.brightness,row_address_type=args.row_address_type,
                            swap_eyes=args.swap_eyes)
        start=time.monotonic()
        try:
            while True:
                now=time.monotonic()
                if args.auto:
                    animator.set_state(STATES[int((now-start)/5)%len(STATES)],now=now)
                output.show(animator.render(now))
                time.sleep(1/30)
        except KeyboardInterrupt:
            pass
        finally:
            output.close()
        return
    import pygame
    pygame.init()
    screen=pygame.display.set_mode((760,430))
    pygame.display.set_caption('Arby · dos matrices de 32×32')
    font=pygame.font.Font(None,27)
    small=pygame.font.Font(None,19)
    clock=pygame.time.Clock()
    grid=False
    automatic=args.auto
    changed=time.monotonic()
    running=True
    try:
        while running:
            now=time.monotonic()
            for event in pygame.event.get():
                if event.type==pygame.QUIT:
                    running=False
                elif event.type==pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
                        running=False
                    elif event.unicode in '1234567890' and event.unicode:
                        index='1234567890'.index(event.unicode)
                        animator.set_state(STATES[index],now=now)
                        automatic=False
                    elif event.key in (pygame.K_d, pygame.K_c):
                        animator.set_state('default' if event.key == pygame.K_d else 'cargando', now=now)
                        automatic=False
                    elif event.key==pygame.K_SPACE:
                        animator.set_state(STATES[(STATES.index(animator.state)+1)%len(STATES)],now=now)
                    elif event.key==pygame.K_a:
                        automatic=not automatic
                        changed=now
                    elif event.key==pygame.K_g:
                        grid=not grid
            if automatic and now-changed>=5:
                animator.set_state(STATES[(STATES.index(animator.state)+1)%len(STATES)],now=now)
                changed=now
            frame=animator.render(now)
            screen.fill((12,18,26))
            screen.blit(font.render(f'Arby / {animator.state}',True,(180,235,255)),(45,23))
            for side,x in enumerate((76,428)):
                panel=frame.crop((side*32,0,side*32+32,32))
                surface=pygame.image.fromstring(panel.tobytes(),panel.size,'RGB')
                screen.blit(pygame.transform.scale(surface,(256,256)),(x,83))
                pygame.draw.rect(screen,(50,70,85),(x-1,82,258,258),1)
                if grid:
                    for i in range(33):
                        pygame.draw.line(screen,(20,30,38),(x+i*8,83),(x+i*8,339))
                        pygame.draw.line(screen,(20,30,38),(x,83+i*8),(x+256,83+i*8))
                label='Panel 1 / izquierda' if side==0 else 'Panel 2 / derecha'
                screen.blit(small.render(label,True,(170,190,205)),(x,355))
            screen.blit(small.render('1–9/0: emociones | D: reposo | C: cargando | Espacio: siguiente | A: auto | G: grid | Esc',
                                   True,(180,195,210)),(45,397))
            pygame.display.flip()
            clock.tick(30)
    finally:
        pygame.quit()


if __name__=='__main__':
    main()
