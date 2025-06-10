import logging  # Add logging module
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import requests
import os
from dotenv import load_dotenv
import openai
from openai.error import AuthenticationError, OpenAIError  # Explicitly import OpenAI error classes
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.responses import PlainTextResponse
from fastapi.responses import JSONResponse  # Fix missing import

# Load environment variables
load_dotenv()

# Validate required environment variables
required_env_vars = ["OPENWEATHER_KEY", "OPENAI_API_KEY"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust origins as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.error("Validation error: %s", exc)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}  # Removed invalid "body" key
    )

# Global exception handler for unexpected errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception occurred: %s", exc)  # Use logger.exception for detailed stack trace
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}  # Include exception details for debugging
    )

@app.get("/")
def read_root() -> dict:
    """Root endpoint to verify the API is running."""
    return {"message": "Hello from Dockerized FastAPI!"}

@app.get("/bmi")
def calculate_bmi(weight: float, height: float) -> dict:
    """
    Calculate the Body Mass Index (BMI).
    :param weight: Weight in kilograms.
    :param height: Height in centimeters.
    :return: BMI value.
    """

    if height <= 0 or weight <= 0:
        raise HTTPException(status_code=400, detail="Weight and height must be greater than zero.")
    # Convert height from centimeters to meters if height > 10 (assuming input is in cm)
    if height > 10:
        height = height / 100
    bmi = weight / (height ** 2)
    return {"bmi": round(bmi, 2)}

@app.get("/calories")
def calculate_calories(weight: float, duration: float, activity_level: str) -> dict:
    """
    Calculate calories burned based on activity level.
    :param weight: Weight in kilograms.
    :param duration: Duration in minutes.
    :param activity_level: Activity level (light, moderate, vigorous).
    :return: Calories burned.
    """
    if duration <= 0 or weight <= 0:
        raise HTTPException(status_code=400, detail="Weight and duration must be greater than zero.")

    met_values = {
        "light": 3.5,
        "moderate": 5.0,
        "vigorous": 8.0
    }

    met = met_values.get(activity_level)
    if not met:
        raise HTTPException(status_code=400, detail="Invalid activity level. Choose from light, moderate, or vigorous.")

    calories_burned = (met * weight * duration) / 60
    return {"calories_burned": round(calories_burned, 2)}

@app.get("/weather")
def get_weather(city: str) -> dict:
    """
    Fetch current weather data for a given city.
    :param city: City name.
    :return: Weather details including temperature and description.
    """
    API_KEY = os.getenv("OPENWEATHER_KEY")
    if not API_KEY:
        logger.error("Missing OpenWeather API key.")
        raise HTTPException(status_code=500, detail="Missing OpenWeather API key.")

    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=10)  # Add timeout for better error handling
        response.raise_for_status()
        data = response.json()
        if "main" not in data or "weather" not in data:
            logger.error("Unexpected response format from OpenWeather API: %s", data)
            raise HTTPException(status_code=500, detail="Unexpected response format from OpenWeather API.")
        return {
            "city": city,
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"]
        }
    except requests.exceptions.Timeout:
        logger.error("OpenWeather API request timed out for city: %s", city)
        raise HTTPException(status_code=504, detail="OpenWeather API request timed out.")
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch weather data for city %s: %s", city, str(e))
        raise HTTPException(status_code=502, detail=f"Bad Gateway: {str(e)}")  # Use 502 for upstream errors
    except Exception as e:
        logger.exception("Unexpected error in /weather endpoint: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")  # Include exception details

# Configure OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.get("/ask-openai")
def ask_openai(request: str) -> dict:
    """
    Interact with OpenAI's API to get a response for a given request.
    :param request: User's input query.
    :return: OpenAI's response.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": request}]
        )
        choices = response.get("choices")
        if not choices or not choices[0].get("message"):
            logger.error("Unexpected response format from OpenAI API: %s", response)
            raise HTTPException(status_code=500, detail="Unexpected response format from OpenAI API.")
        return {"response": choices[0]["message"]["content"]}
    except AuthenticationError:
        logger.error("Invalid OpenAI API key.")
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.")
    except OpenAIError as e:
        logger.error("OpenAI API error: %s", str(e))
        raise HTTPException(status_code=502, detail=f"Bad Gateway: {str(e)}")
    except Exception as e:
        logger.exception("Unexpected error in /ask-openai endpoint: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@app.get("/hydration")
def check_hydration(water_ml: int) -> dict:
    """
    Check hydration status based on water intake.
    :param water_ml: Amount of water consumed in milliliters.
    :return: Hydration status.
    """
    if water_ml < 2000:
        return {"status": "Drink more water!", "advice": "Aim for at least 2 liters per day."}
    elif 2000 <= water_ml <= 3000:
        return {"status": "You're well hydrated!", "advice": "Maintain this level of hydration."}
    else:
        return {"status": "Too much water!", "advice": "Avoid overhydration."}

@app.get("/sleep-score")
def sleep_score(hours: float) -> dict:
    """
    Calculate sleep score based on hours slept.
    :param hours: Hours of sleep.
    :return: Sleep score and status.
    """
    if hours < 6:
        return {"score": 50, "status": "Too little sleep"}
    elif 6 <= hours <= 8:
        return {"score": 90, "status": "Healthy sleep"}
    else:
        return {"score": 70, "status": "Too much sleep"}