import os
import cv2
import requests
from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.utils import secure_filename
from ultralytics import YOLO

# Configuration
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Load YOLO model 
# 'yolov8n.pt' is the Nano version – fast and lightweight
model = YOLO("yolov8n.pt")

# USDA API Configuration
USDA_API_KEY = "d6SFinftapye3MhtGNUcEOD2PVeJUIJtJ19mBGle"  
USDA_API_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# Simple in-memory cache to avoid repeated API calls for the same food
calorie_cache = {}

def get_calories_from_usda(food_name):
    """
    Fetch calories (per 100g) for a given food name from USDA API.
    Returns an integer calorie value, or 0 if not found.
    """
    # 1. Check cache first
    if food_name in calorie_cache:
        return calorie_cache[food_name]

    # 2. Prepare API request
    params = {
        "api_key": USDA_API_KEY,
        "query": food_name,
        "pageSize": 1  # only need the top match
    }

    try:
        response = requests.get(USDA_API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get('foods'):
            # Take the first result
            food = data['foods'][0]
            # Look for 'Energy' nutrient (calories)
            for nutrient in food.get('foodNutrients', []):
                if nutrient.get('nutrientName') == 'Energy':
                    calories = nutrient.get('value')
                    if calories is not None:
                        # Store in cache
                        calorie_cache[food_name] = calories
                        return calories
            # If no Energy nutrient found, try 'Calories' as fallback
            for nutrient in food.get('foodNutrients', []):
                if nutrient.get('nutrientName') == 'Calories':
                    calories = nutrient.get('value')
                    if calories is not None:
                        calorie_cache[food_name] = calories
                        return calories

        # If we reach here, no calorie data found
        calorie_cache[food_name] = 0
        return 0

    except requests.exceptions.RequestException as e:
        print(f"USDA API error for '{food_name}': {e}")
        calorie_cache[food_name] = 0
        return 0

def detect_food_and_calories(image_path, output_path):
    """
    Run YOLOv8 detection, annotate image, and return detections with calories.
    """
    results = model(image_path)
    detections = []
    total_calories = 0
    img = cv2.imread(image_path)

    # YOLO class names (COCO dataset)
    food_related_classes = {
        'apple', 'banana', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza',
    'donut', 'cake', 'sandwich', 'burger', 'ice cream',
    'french fries'
    }

    for result in results:
        boxes = result.boxes
        for box in boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id].lower()
            confidence = float(box.conf[0])

            # Only process if it's a food item (or you can process everything)
            # For better accuracy, filter by food_related_classes
            if class_name not in food_related_classes:
                continue

            # Get calories from USDA API
            calories = get_calories_from_usda(class_name)
            if calories > 0:
                total_calories += calories
                detections.append({
                    'name': class_name.title(),
                    'confidence': round(confidence, 2),
                    'calories': calories
                })

                # Draw bounding box and label
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 255), 2)
                label = f"{class_name} ({calories} cal)"
                cv2.putText(img, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    cv2.imwrite(output_path, img)
    return detections, total_calories

# Flask Routes
@app.route('/')
def index():
    """Serve the frontend HTML page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_image():
    """Handle image upload, run detection, return JSON results."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Save uploaded file
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)

    # Prepare output path for annotated image
    output_filename = f"annotated_{filename}"
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

    try:
        detections, total_calories = detect_food_and_calories(input_path, output_path)
        return jsonify({
            'success': True,
            'detections': detections,
            'total_calories': total_calories,
            'annotated_image_url': f'/uploads/{output_filename}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve annotated images."""
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

# Run the App
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)