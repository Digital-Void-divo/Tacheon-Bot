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
        # Resize avatar to 300x300
        avatar = avatar.resize((300, 300), Image.Resampling.LANCZOS)
        
        # Create circular mask for avatar
        mask = Image.new('L', (300, 300), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, 300, 300), fill=255)
        avatar.putalpha(mask)
        
        # Use even larger font sizes
        font = ImageFont.load_default(size=60)  # Increased from 40
        username_font = ImageFont.load_default(size=40)  # Increased from 32
        
        # Calculate text dimensions and wrap text
        bubble_width = bubble.width
        max_text_width = bubble_width - 200  # More padding for centering
        
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
        
        # Calculate required bubble height (less tall)
        line_height = 70  # Increased from 50
        text_height = len(lines) * line_height
        min_bubble_height = text_height + 200  # Padding
        
        # Scale bubble to better proportions (less tall)
        target_bubble_height = min(min_bubble_height, bubble.height * 0.7)  # Cap at 70% of original height
        if target_bubble_height < min_bubble_height:
            target_bubble_height = min_bubble_height
        
        scale_factor = target_bubble_height / bubble.height
        new_height = int(bubble.height * scale_factor)
        bubble = bubble.resize((int(bubble_width * scale_factor), new_height), Image.Resampling.LANCZOS)
        
        # Update bubble_width after resize
        bubble_width = bubble.width
        
        # Create final canvas - avatar bottom aligned with bubble
        canvas_width = 350 + bubble.width
        canvas_height = max(400, new_height + 100)  # Extra space for username
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Position bubble first (centered vertically)
        bubble_y = 50
        canvas.paste(bubble, (325, bubble_y), bubble)
        
        # Position avatar lower - aligned with bottom of bubble
        avatar_y = bubble_y + new_height - 200  # Avatar bottom aligns near bubble bottom
        canvas.paste(avatar, (25, avatar_y), avatar)
        
        # Draw text centered in bubble
        draw = ImageDraw.Draw(canvas)
        text_start_y = bubble_y + (new_height - text_height) // 2
        
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            text_x = 325 + (bubble_width - text_width) // 2
            text_y = text_start_y + (i * line_height)
            
            # Draw text with white color
            draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        
        # Draw username below avatar
        name_bbox = draw.textbbox((0, 0), user.display_name, font=username_font)
        name_width = name_bbox[2] - name_bbox[0]
        name_x = 175 - (name_width // 2)
        name_y = avatar_y + 320
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
