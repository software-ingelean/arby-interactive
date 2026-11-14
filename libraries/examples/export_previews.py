"""Export exact-pixel GIF loops and an animated comparison board."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from libraries.eyes.arby_eyes import EyeAnimator, STATES


def main():
    folder=Path(__file__).resolve().parents[2]/'previews'
    folder.mkdir(exist_ok=True)
    try:
        title=ImageFont.truetype('DejaVuSans.ttf',22)
        text=ImageFont.truetype('DejaVuSans.ttf',16)
    except OSError:
        title=text=ImageFont.load_default()
    animators=[EyeAnimator(state) for state in STATES]
    boards=[]
    all_frames=[[] for _ in STATES]
    # Shared fixed palette avoids GIF quantization changing the art.
    palette=Image.new('P',(1,1))
    colors=[(0,0,0),(12,18,26),(180,235,255),(135,240,255),(40,215,255),
            (0,5,12),(245,255,255),(50,70,85),(170,190,205)]
    palette.putpalette(sum((list(c) for c in colors),[])+[0]*(768-len(colors)*3))
    for i in range(100):
        t=i/20
        board=Image.new('RGB',(720, 104 + ((len(STATES)+1)//2)*134),(12,18,26))
        draw=ImageDraw.Draw(board)
        draw.text((24,14),'ARBY / 32 × 32 por ojo y ceja',font=title,fill=(180,235,255))
        draw.text((24,44),'Resolución real ampliada sin suavizado · dos paneles por expresión',font=text,fill=(170,190,205))
        for idx,animator in enumerate(animators):
            frame=animator.render(t)
            all_frames[idx].append(frame.quantize(palette=palette,dither=Image.Dither.NONE))
            x=24+(idx%2)*350
            y=84+(idx//2)*134
            draw.text((x,y),f'{idx+1:02d}  {STATES[idx]}',font=text,fill=(180,235,255))
            for side in (0,1):
                panel=frame.crop((side*32,0,side*32+32,32)).resize((96,96),Image.Resampling.NEAREST)
                board.paste(panel,(x+40+side*130,y+25))
                draw.rectangle((x+39+side*130,y+24,x+136+side*130,y+121),outline=(50,70,85))
        boards.append(board.quantize(palette=palette,dither=Image.Dither.NONE))
    boards[0].save(folder/'expressions.gif',save_all=True,append_images=boards[1:],duration=50,loop=0,optimize=False)
    boards[0].convert('RGB').save(folder/'expressions.png')
    for state,frames in zip(STATES,all_frames):
        name=state.replace(' ','_').replace('ñ','n')
        frames[0].save(folder/f'{name}_64x32.gif',save_all=True,append_images=frames[1:],duration=50,loop=0,optimize=False)
    print('Previews:',folder)


if __name__=='__main__':
    main()
