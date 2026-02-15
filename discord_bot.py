async def generate_quote_image(user: discord.Member, quote_text: str) -> bytes:
    """Generate a quote image with user avatar and speech bubble"""
    
    try:
        # Download user avatar
        async with aiohttp.ClientSession() as session:
            print(f"Downloading avatar from: {user.display_avatar.url}")
            async with session.get(str(user.display_avatar.url)) as resp:
                print(f"Avatar download status: {resp.status}")
                avatar_bytes = await resp.read()
            
            # Download speech bubble
            print(f"Downloading bubble from: {SPEECH_BUBBLE_IMAGE}")
            async with session.get(SPEECH_BUBBLE_IMAGE) as resp:
                print(f"Bubble download status: {resp.status}")
                if resp.status != 200:
                    raise Exception(f"Failed to download bubble: HTTP {resp.status}")
                bubble_bytes = await resp.read()
        
        print("Opening images with PIL...")
        # Open images
        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        bubble = Image.open(BytesIO(bubble_bytes)).convert("RGBA")
        
        print("Resizing avatar...")
        # Resize avatar to 150x150
        avatar = avatar.resize((150, 150), Image.Resampling.LANCZOS)
        
        # Create circular mask for avatar
        mask = Image.new('L', (150, 150), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, 150, 150), fill=255)
        avatar.putalpha(mask)
        
        # Load pixel font (using default if custom not available)
        try:
            # Try to use a pixel-style font
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        # Calculate text dimensions and wrap text
        bubble_width = bubble.width
        max_text_width = bubble_width - 100  # Padding
        
        # Wrap text
        lines = []
        words = quote_text.split()
        current_line = ""
        
        draw_temp = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        for word in words:
            test_line = current_line + word + " "
            bbox = draw_temp.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_text_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
        
        # Calculate required bubble height
        line_height = 35
        text_height = len(lines) * line_height
        min_bubble_height = text_height + 100  # Add padding
        
        # Expand bubble vertically if needed
        if min_bubble_height > bubble.height:
            # Scale bubble to fit text
            scale_factor = min_bubble_height / bubble.height
            new_height = int(bubble.height * scale_factor)
            bubble = bubble.resize((bubble_width, new_height), Image.Resampling.LANCZOS)
        
        # Create final canvas
        canvas_width = 200 + bubble.width  # Avatar space + bubble
        canvas_height = max(200, bubble.height)  # At least avatar height
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Paste avatar on left
        avatar_y = (canvas_height - 150) // 2
        canvas.paste(avatar, (25, avatar_y), avatar)
        
        # Paste bubble
        bubble_y = (canvas_height - bubble.height) // 2
        canvas.paste(bubble, (175, bubble_y), bubble)
        
        # Draw text centered in bubble
        draw = ImageDraw.Draw(canvas)
        text_start_y = bubble_y + (bubble.height - text_height) // 2
        
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = 175 + (bubble.width - text_width) // 2
            text_y = text_start_y + (i * line_height)
            
            # Draw text with white color
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        
        # Draw username below avatar
        username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        name_bbox = draw.textbbox((0, 0), user.display_name, font=username_font)
        name_width = name_bbox[2] - name_bbox[0]
        name_x = 100 - (name_width // 2)
        name_y = avatar_y + 160
        draw.text((name_x, name_y), user.display_name, font=username_font, fill=(255, 255, 255, 255))
        
        # Save to bytes
        print("Saving to PNG...")
        output = BytesIO()
        canvas.save(output, format='PNG')
        output.seek(0)
        print("Quote image generated successfully!")
        return output.getvalue()
        
    except Exception as e:
        print(f"Error in generate_quote_image: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise
